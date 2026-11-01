"""Raster analyses used by both the Streamlit app and the agent."""
import numpy as np
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform

import metrics
from store import to_geotiff_bytes


def _projected_metres(r):
    c = r.crs
    if c is None:
        raise ValueError("Raster has no CRS.")
    if not c.is_projected:
        raise ValueError("Raster CRS is geographic. Reproject to a projected CRS in metres first.")
    if str(c.linear_units or "").lower() not in ("metre", "meter", "metres", "meters"):
        raise ValueError(f"CRS units are '{c.linear_units}', not metres.")


def inspect(store, name):
    r = store.get(name)
    t, v = r.transform, r.data[~r.mask]
    out = dict(layer=name, crs=r.crs.to_string() if r.crs else None, size_cols_rows=[r.data.shape[1], r.data.shape[0]],
               pixel_size=[t.a, t.e], origin=[t.c, t.f], nodata=r.nodata, dtype=str(r.data.dtype), valid_pixels=int(v.size))
    if v.size:
        out.update(min=float(v.min()), max=float(v.max()))
        u = np.unique(v)
        if r.data.dtype.kind in "iu" and u.size <= 50:
            out["class_values"] = u.tolist()
    return out


def geometry_match(store, names):
    ref = store.get(names[0])
    rows = []
    for n in names[1:]:
        r = store.get(n)
        tol = 1e-6 * abs(ref.transform.a)
        res = dict(layer=n, crs=bool(ref.crs == r.crs),
                   cell_size=bool(np.isclose(ref.transform.a, r.transform.a, rtol=1e-9) and np.isclose(ref.transform.e, r.transform.e, rtol=1e-9)),
                   rows_cols=ref.data.shape == r.data.shape,
                   origin=bool(abs(ref.transform.c - r.transform.c) <= tol and abs(ref.transform.f - r.transform.f) <= tol))
        if res["rows_cols"]:
            res["nodata_mask_mismatch_pixels"] = int((ref.mask != r.mask).sum())
        res["match"] = all(res[k] for k in ("crs", "cell_size", "rows_cols", "origin"))
        rows.append(res)
    return dict(reference=names[0], results=rows, all_match=all(x["match"] for x in rows))


def area_stats(store, name, labels=None):
    r = store.get(name)
    _projected_metres(r)
    pa = abs(r.transform.a * r.transform.e)
    v, c = np.unique(r.data[~r.mask], return_counts=True)
    ha = metrics.area_ha(c, pa)
    tot = sum(ha)
    return dict(layer=name, pixel_area_m2=pa, total_ha=tot, classes=[
        dict(code=int(k), name=(labels or {}).get(str(int(k))), pixels=int(n), area_ha=h, percent=h / tot * 100)
        for k, n, h in zip(v, c, ha)])


def _pair(store, a, b):
    x, y = store.get(a), store.get(b)
    if x.data.shape != y.data.shape:
        raise ValueError("Rasters differ in size. Run the geometry check and align them first.")
    return x, y, ~(x.mask | y.mask)


def transition_matrix(store, old, new):
    x, y, ok = _pair(store, old, new)
    _projected_metres(x)
    mat, cls = metrics.confusion_matrix(x.data[ok], y.data[ok])
    ha = np.array(metrics.area_ha(mat.ravel(), abs(x.transform.a * x.transform.e))).reshape(mat.shape)
    off = sorted(((float(ha[i, j]), cls[i], cls[j]) for i in range(len(cls)) for j in range(len(cls)) if i != j and ha[i, j] > 0), reverse=True)
    return dict(classes=cls, matrix_ha=ha.round(2).tolist(), rows="old", cols="new",
                persistence_percent=float(np.trace(ha) / ha.sum() * 100),
                top_conversions=[dict(area_ha=round(a, 2), from_code=f, to_code=t) for a, f, t in off[:10]],
                note="Net change hides gross transitions; inspect implausible conversions for classification or registration errors.")


def accuracy_points(store, raster, table, ref_col, x_col, y_col, epsg=None):
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
        raise ValueError(f"Only {len(ref)} usable validation points; far more are needed for a defensible assessment.")
    mat, cls = metrics.confusion_matrix(ref, pred)
    res = metrics.accuracy_from_matrix(mat)
    res.update(classes=cls, confusion_matrix_rows_reference_cols_predicted=mat.tolist(), points_skipped=skipped,
               warning="Validation points must be independent of training data; small classes give wide uncertainty.")
    return res


def hindcast(store, observed, simulated, initial=None):
    o, s, ok = _pair(store, observed, simulated)
    if initial:
        i = store.get(initial)
        if i.data.shape != o.data.shape:
            raise ValueError("Initial raster differs in size.")
        ok = ok & ~i.mask
    mat, cls = metrics.confusion_matrix(o.data[ok], s.data[ok])
    res = metrics.accuracy_from_matrix(mat)
    res.update(classes=cls, disagreement=metrics.pontius_disagreement(mat), compared_pixels=int(ok.sum()))
    if initial:
        res["figure_of_merit"] = metrics.figure_of_merit(store.get(initial).data[ok], o.data[ok], s.data[ok])
    res["interpretation_note"] = ("High overall agreement can come from persistence alone. Use figure of merit and the quantity/allocation "
                                  "split, and map disagreement before moving to future scenarios.")
    return res


def spectral_index(store, index, band_a, band_b, out_name):
    """NDVI=(NIR-Red)/(NIR+Red); NDWI=(Green-NIR)/(Green+NIR); NDBI=(SWIR-NIR)/(SWIR+NIR). band_a is the first operand."""
    if index not in ("NDVI", "NDWI", "NDBI"):
        raise ValueError("index must be NDVI, NDWI or NDBI")
    a, b, ok = _pair(store, band_a, band_b)
    x, y = a.data.astype("float32"), b.data.astype("float32")
    den = x + y
    bad = ~ok | (den == 0)
    res = np.where(bad, -9999, (x - y) / np.where(den == 0, 1, den)).astype("float32")
    store.outputs[out_name] = to_geotiff_bytes(a.profile, res, "float32", -9999)
    v = res[~bad]
    return dict(output=out_name, index=index, min=float(v.min()) if v.size else None, max=float(v.max()) if v.size else None,
                note="Indices are classification aids, not class labels. Confirm the band order matches your sensor.")


def transition_raster(store, old, new, out_name, multiplier=10):
    x, y, ok = _pair(store, old, new)
    if max(int(x.data[ok].max()), int(y.data[ok].max())) >= multiplier:
        raise ValueError("Multiplier must be larger than the largest class code, otherwise codes are ambiguous.")
    res = np.where(ok, x.data.astype("int32") * multiplier + y.data.astype("int32"), -9999)
    store.outputs[out_name] = to_geotiff_bytes(x.profile, res, "int32", -9999)
    return dict(output=out_name, encoding=f"old*{multiplier}+new")


def disagreement_raster(store, observed, simulated, out_name):
    o, s, ok = _pair(store, observed, simulated)
    res = np.where(ok, (o.data != s.data).astype("uint8"), 255)
    store.outputs[out_name] = to_geotiff_bytes(o.profile, res, "uint8", 255)
    return dict(output=out_name, disagreement_pixels=int(((o.data != s.data) & ok).sum()))
