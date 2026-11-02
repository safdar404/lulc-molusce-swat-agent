"""Advanced accuracy and change analyses on the in-memory raster store (v0.6.0).

* Area-adjusted accuracy (Olofsson et al. 2014) from a classified raster + validation table
* Accuracy sample design and stratified random point generation
* Multi-date Intensity Analysis (Aldwaik & Pontius 2012) with change components and alternation
* Change-frequency and category-trajectory rasters (Pontius et al. 2017)

Class areas use the exact cell area of projected rasters and spherical cell areas for geographic (lat/lon) rasters.
"""
import re

import numpy as np
import pandas as pd
from rasterio.transform import rowcol, xy
from rasterio.warp import transform as warp_transform

import intensity as ia
import olofsson
from store import to_geotiff_bytes

UNITS = {"ha": 1e-4, "km2": 1e-6, "m2": 1.0}
_R = 6_371_008.8


def _unit(unit):
    if unit not in UNITS:
        raise ValueError(f"area unit must be one of {list(UNITS)}")
    return UNITS[unit]


def row_cell_area_m2(r):
    """Cell area (m²) for every row of a raster."""
    t, nrows = r.transform, r.data.shape[0]
    if r.crs is None:
        raise ValueError("Raster has no CRS; areas cannot be computed.")
    if r.crs.is_geographic:
        rows = np.arange(nrows)
        lat0, lat1 = np.radians(t.f + rows * t.e), np.radians(t.f + (rows + 1) * t.e)
        return _R**2 * np.radians(abs(t.a)) * np.abs(np.sin(lat0) - np.sin(lat1))
    f = r.crs.linear_units_factor[1] if r.crs.linear_units_factor else 1.0
    return np.full(nrows, abs(t.a * t.e) * f * f)


def _int_classes(r, valid):
    v = r.data[valid]
    if r.data.dtype.kind == "f":
        if v.size and not np.all(np.mod(v, 1) == 0):
            raise ValueError(f"{r.name} has non-integer values; a categorical LULC raster is required.")
    return v.astype(np.int64)


def class_area(r, unit="ha", valid=None):
    valid = ~r.mask if valid is None else valid
    w = np.broadcast_to(row_cell_area_m2(r)[:, None], r.data.shape)[valid] * _unit(unit)
    v = _int_classes(r, valid)
    u, inv = np.unique(v, return_inverse=True)
    return dict(zip(u.tolist(), np.bincount(inv, weights=w).tolist())), dict(zip(u.tolist(), np.bincount(inv).tolist()))


def _year_guess(name, default):
    m = re.search(r"(19|20)\d{2}", name)
    return int(m.group(0)) if m else default


def _same_grid(rasters):
    ref = rasters[0]
    for r in rasters[1:]:
        if r.data.shape != ref.data.shape or r.crs != ref.crs or not np.allclose(tuple(r.transform)[:6], tuple(ref.transform)[:6]):
            raise ValueError(f"{r.name} is not on the same grid as {ref.name}. Run the geometry check and align the rasters first.")


# ------------------------------------------------------------------ accuracy
def area_adjusted_accuracy(store, raster, table, ref_col, x_col, y_col, epsg=None, unit="ha", labels=None):
    r = store.get(raster)
    df = table.dropna(subset=[ref_col, x_col, y_col])
    xs, ys = df[x_col].astype(float).tolist(), df[y_col].astype(float).tolist()
    if epsg and r.crs and str(r.crs.to_epsg()) != str(int(epsg)):
        xs, ys = warp_transform(f"EPSG:{int(epsg)}", r.crs, xs, ys)
    rows, cols = rowcol(r.transform, xs, ys)
    ref, pred, skipped = [], [], len(table) - len(df)
    for rv, i, j in zip(df[ref_col].tolist(), rows, cols):
        if 0 <= i < r.data.shape[0] and 0 <= j < r.data.shape[1] and not r.mask[i, j]:
            ref.append(int(rv))
            pred.append(int(r.data[i, j]))
        else:
            skipped += 1
    if len(ref) < 10:
        raise ValueError(f"Only {len(ref)} usable validation points; far more are needed.")
    areas, _ = class_area(r, unit)
    classes = sorted(set(areas) | set(ref))
    n = olofsson.sample_error_matrix(pred, ref, classes)
    names = [f"{c} {(labels or {}).get(str(c), '')}".strip() for c in classes]
    res = olofsson.olofsson_accuracy(n, [areas.get(c, 0.0) for c in classes], names, unit)
    out = res.summary()
    out.update(points_used=len(ref), points_skipped=skipped,
               sample_matrix=res.sample_matrix_df().reset_index().to_dict(orient="list"),
               proportion_matrix=res.proportion_matrix_df().round(6).reset_index().to_dict(orient="list"),
               pontius_per_class=res.pontius["per_class"].round(6).to_dict(orient="records"),
               methods_text=res.methods_text(),
               note="Valid only if points are a (stratified) random sample independent of training data. "
                    "Report the error-adjusted areas, not pixel counts.")
    return out


def design_sample(store, raster, expected_ua=0.85, target_se=0.01, allocation="olofsson", min_per_class=50, unit="ha"):
    r = store.get(raster)
    areas, pix = class_area(r, unit)
    cls = list(areas)
    ua = [float(expected_ua.get(str(c), 0.85)) if isinstance(expected_ua, dict) else float(expected_ua) for c in cls]
    d = olofsson.sample_size_design([areas[c] for c in cls], ua, target_se, allocation, min_per_class, cls)
    d["mapped_area"], d["available_pixels"] = [areas[c] for c in cls], [pix[c] for c in cls]
    d["n_samples"] = np.minimum(d["n_samples"], d["available_pixels"])
    return dict(raster=raster, area_unit=unit, n_total_formula=int(d["n_total_formula"].iloc[0]),
                n_allocated=int(d["n_samples"].sum()), design=d.drop(columns="n_total_formula").round(4).to_dict(orient="records"),
                note="Olofsson et al. (2014) Eq. 13. Expected user's accuracies are your prior guesses; rare classes get a minimum sample.")


def sample_points(store, raster, n_per_class, seed=42):
    r = store.get(raster)
    rng = np.random.default_rng(int(seed))
    rows_out = []
    data = r.data
    for c, n in n_per_class.items():
        rr, cc = np.nonzero((data == int(c)) & ~r.mask)
        if rr.size == 0:
            continue
        k = rng.choice(rr.size, size=min(int(n), rr.size), replace=False)
        xs, ys = xy(r.transform, rr[k], cc[k], offset="center")
        for x, y in zip(np.atleast_1d(xs), np.atleast_1d(ys)):
            rows_out.append((int(c), float(x), float(y)))
    df = pd.DataFrame(rows_out, columns=["map_class", "x", "y"])
    if len(df) and r.crs is not None and not r.crs.is_geographic:
        lon, lat = warp_transform(r.crs, "EPSG:4326", df["x"].tolist(), df["y"].tolist())
        df["lon"], df["lat"] = lon, lat
    df = df.sample(frac=1, random_state=int(seed)).reset_index(drop=True)
    df.insert(0, "point_id", np.arange(1, len(df) + 1))
    df["reference_class"] = ""
    return df


# ------------------------------------------------------------------ change
def _stack(store, layers):
    if len(layers) < 2:
        raise ValueError("Select at least two LULC rasters in date order.")
    rs = [store.get(n) for n in layers]
    _same_grid(rs)
    valid = np.logical_and.reduce([~r.mask for r in rs])
    if not valid.any():
        raise ValueError("No pixel is valid in all selected rasters.")
    return rs, valid


def intensity_analysis(store, layers, years=None, unit="ha", labels=None):
    rs, valid = _stack(store, layers)
    years = list(years) if years else [_year_guess(n, i) for i, n in enumerate(layers)]
    if len(years) != len(layers):
        raise ValueError("Give one year per raster.")
    order = np.argsort(years)
    rs, years, layers = [rs[i] for i in order], [years[i] for i in order], [layers[i] for i in order]
    w = np.broadcast_to(row_cell_area_m2(rs[0])[:, None], valid.shape)[valid] * _unit(unit)
    vals = [_int_classes(r, valid) for r in rs]
    classes = sorted(set(np.unique(np.concatenate(vals)).tolist()))
    idx = [np.searchsorted(classes, v) for v in vals]
    k = len(classes)
    mats = [np.bincount(idx[t] * k + idx[t + 1], weights=w, minlength=k * k).reshape(k, k) for t in range(len(rs) - 1)]
    extent = np.bincount(idx[0] * k + idx[-1], weights=w, minlength=k * k).reshape(k, k)
    names = [f"{c} {(labels or {}).get(str(c), '')}".strip() for c in classes]
    res = ia.add_extent_components(ia.intensity_analysis(mats, years, names, unit), extent)
    return dict(layers=layers, years=years, area_unit=unit, classes=names,
                uniform_intensity_pct_per_year=round(res.uniform_U, 4),
                interval=res.interval.round(4).to_dict(orient="records"),
                category=res.category.round(4).to_dict(orient="records"),
                transition_gain=res.transition_gain.round(4).to_dict(orient="records"),
                transition_loss=res.transition_loss.round(4).to_dict(orient="records"),
                stationarity_category=res.stationarity_category.to_dict(orient="records"),
                stationarity_transition=res.stationarity_transition.to_dict(orient="records"),
                components=res.components.round(4).to_dict(orient="records"),
                matrices=[m.round(4).tolist() for m in mats],
                methods_text=res.methods_text(),
                note="Intensities are % per year. Deviations from uniform can also come from map error; check accuracy first "
                     "(Aldwaik & Pontius 2013).")


TRAJ = {0: "nodata", 1: "stable absence", 2: "stable presence", 3: "gain without alternation", 4: "loss without alternation",
        5: "gain with alternation", 6: "loss with alternation", 7: "alternation, gain first", 8: "alternation, loss first"}


def change_frequency_raster(store, layers, out_name):
    rs, valid = _stack(store, layers)
    cnt = np.zeros(valid.shape, "uint8")
    for a, b in zip(rs, rs[1:]):
        cnt += (a.data != b.data).astype("uint8")
    out = np.where(valid, cnt, 255).astype("uint8")
    store.outputs[out_name] = to_geotiff_bytes(rs[0].profile, out, "uint8", 255)
    u, c = np.unique(cnt[valid], return_counts=True)
    return dict(output=out_name, intervals=len(rs) - 1,
                pixels_by_number_of_changes={int(k): int(v) for k, v in zip(u, c)},
                note="0 = never changed; n = changed in n intervals. Many changes in a short time often indicate classification noise.")


def trajectory_raster(store, layers, category, out_name, unit="ha"):
    rs, valid = _stack(store, layers)
    pres = np.stack([r.data == int(category) for r in rs])
    first, last = pres[0], pres[-1]
    nchg = (pres[1:] != pres[:-1]).sum(0)
    code = np.zeros(valid.shape, "uint8")
    code[(nchg == 0) & ~first] = 1
    code[(nchg == 0) & first] = 2
    code[(nchg == 1) & ~first & last] = 3
    code[(nchg == 1) & first & ~last] = 4
    code[(nchg > 1) & ~first & last] = 5
    code[(nchg > 1) & first & ~last] = 6
    code[(nchg > 1) & ~first & ~last] = 7
    code[(nchg > 1) & first & last] = 8
    code[~valid] = 0
    store.outputs[out_name] = to_geotiff_bytes(rs[0].profile, code, "uint8", 0)
    w = np.broadcast_to(row_cell_area_m2(rs[0])[:, None], valid.shape) * _unit(unit)
    areas = {TRAJ[k]: float(w[(code == k) & valid].sum()) for k in range(1, 9)}
    return dict(output=out_name, category=int(category), area_unit=unit, legend=TRAJ, area_by_trajectory=areas,
                note="Trajectories follow Pontius et al. (2017). Alternation means the category was gained and lost "
                     "(or lost and regained) within the period.")
