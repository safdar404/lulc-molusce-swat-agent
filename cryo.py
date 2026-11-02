"""Snow, ice and elevation-zone analysis for mountain basins (v1.4.0).

* Hypsometry: area per elevation band, hypsometric curve, hypsometric integral (Strahler 1952), custom elevation zones
  (e.g. the five zones used for snowmelt-runoff modelling)
* Snow and ice mapping from a composite with the Normalised Difference Snow Index, NDSI = (green - SWIR1) / (green + SWIR1),
  snow where NDSI > 0.4 and NIR reflectance > 0.11 (Hall et al. 1995; Dozier 1989); optional water mask
* Elevation-zone statistics of any class map (snow, glaciers, land cover): area and share per zone, and the snowline altitude where
  the snow-covered share of a band crosses 50 %

Areas use the exact cell area (projected grids) or spherical cell areas (lat/lon grids). A basin polygon can clip every analysis.
"""
import numpy as np
import pandas as pd
from rasterio import features

from changeops import row_cell_area_m2
from store import to_geotiff_bytes


def _clip_mask(r, gdf):
    """True inside the polygon(s) on the grid of raster r (all True if gdf is None)."""
    if gdf is None:
        return np.ones(r.data.shape, bool)
    g = gdf.to_crs(r.crs) if r.crs is not None and gdf.crs != r.crs else gdf
    geoms = [x for x in g.geometry if x is not None and not x.is_empty]
    if not geoms:
        raise ValueError("The clip layer has no polygons.")
    return features.geometry_mask(geoms, out_shape=r.data.shape, transform=r.transform, invert=True)


def _edges(zmin, zmax, band_m=500.0, zones=None):
    if zones:
        e = sorted(float(z) for z in zones)
        return np.array([min(zmin, e[0])] + [x for x in e if zmin < x < zmax] + [zmax + 1e-6])
    lo = np.floor(zmin / band_m) * band_m
    hi = max(np.ceil(zmax / band_m) * band_m, lo + band_m)   # the top value falls in the last band
    return np.arange(lo, hi + band_m / 2, band_m)


def hypsometry(store, dem, band_m=500.0, zones=None, clip=None):
    r = store.get(dem)
    m = ~r.mask & _clip_mask(r, clip)
    z = r.data.astype("float64")[m]
    if z.size == 0:
        raise ValueError("No valid DEM cells inside the area.")
    w = np.broadcast_to(row_cell_area_m2(r)[:, None], r.data.shape)[m] / 1e6       # km2
    e = _edges(float(z.min()), float(z.max()), float(band_m), zones)
    idx = np.clip(np.searchsorted(e, z, side="right") - 1, 0, len(e) - 2)
    area = np.bincount(idx, weights=w, minlength=len(e) - 1)
    tot = area.sum()
    tab = pd.DataFrame({"from_m": e[:-1].round(0), "to_m": e[1:].round(0), "area_km2": area, "area_pct": area / tot * 100})
    tab["cumulative_km2"] = tab["area_km2"].cumsum()
    tab["cumulative_pct"] = tab["cumulative_km2"] / tot * 100
    zmin, zmax, zmean = float(z.min()), float(z.max()), float(np.average(z, weights=w))
    order = np.argsort(z)
    cum = np.cumsum(w[order]) / tot
    q = {f"p{p}": float(z[order][np.searchsorted(cum, p / 100)]) for p in (5, 25, 50, 75, 95)}
    # hypsometric curve: relative area above each relative elevation (Strahler 1952)
    rel_h = np.linspace(0, 1, 51)
    above = [float(w[z >= zmin + h * (zmax - zmin)].sum() / tot) for h in rel_h]
    return dict(dem=dem, clipped=clip is not None, area_km2=float(tot), min_m=zmin, max_m=zmax, mean_m=zmean, median_m=q["p50"], percentiles_m=q,
                hypsometric_integral=float((zmean - zmin) / (zmax - zmin)) if zmax > zmin else None,
                bands=tab.round(3).to_dict(orient="records"), curve=dict(relative_height=rel_h.round(3).tolist(), relative_area_above=np.round(above, 4).tolist()),
                note="Hypsometric integral > 0.6: youthful, little-eroded relief; < 0.35: mature. Copernicus DEM is a surface model (includes ice and canopy).")


def snow_map(store, band_map, scale=1e-4, offset=0.0, ndsi_threshold=0.4, nir_threshold=0.11, water_layer=None, water_classes=(80,), clip=None,
             output_name="snow_ice.tif"):
    """Binary snow / ice map (1 = snow or ice, 2 = snow-free, 0 = no data) from green, SWIR1 and NIR bands."""
    need = [k for k in ("green", "swir1", "nir") if k not in band_map]
    if need:
        raise ValueError(f"Snow mapping needs bands {need} in band_map (green, swir1, nir).")
    g, s, n = (store.get(band_map[k]) for k in ("green", "swir1", "nir"))
    if not (g.data.shape == s.data.shape == n.data.shape):
        raise ValueError("Green, SWIR1 and NIR must be on one grid.")
    valid = ~(g.mask | s.mask | n.mask) & _clip_mask(g, clip)
    G, S, N = (x.data.astype("float32") * scale + offset for x in (g, s, n))
    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = (G - S) / (G + S)
    snow = valid & np.isfinite(ndsi) & (ndsi > ndsi_threshold) & (N > nir_threshold)
    if water_layer:
        w = store.get(water_layer)
        if w.data.shape != g.data.shape:
            raise ValueError("Water layer must be on the composite's grid (download WorldCover with the composite as template).")
        snow &= ~np.isin(w.data, list(water_classes))
    out = np.where(valid, np.where(snow, 1, 2), 0).astype("uint8")
    store.outputs[output_name] = to_geotiff_bytes(g.profile, out, "uint8", 0)
    ca = np.broadcast_to(row_cell_area_m2(g)[:, None], out.shape) / 1e6
    snow_km2, valid_km2 = float(ca[out == 1].sum()), float(ca[valid].sum())
    ndsi_out = np.where(valid & np.isfinite(ndsi), ndsi, -9999).astype("float32")
    nname = output_name.rsplit(".", 1)[0] + "_NDSI.tif"
    store.outputs[nname] = to_geotiff_bytes(g.profile, ndsi_out, "float32", -9999)
    return dict(output=output_name, ndsi_output=nname, snow_ice_km2=snow_km2, mapped_km2=valid_km2, snow_ice_pct=snow_km2 / valid_km2 * 100 if valid_km2 else None,
                ndsi_threshold=ndsi_threshold, nir_threshold=nir_threshold, water_masked=bool(water_layer), labels={"1": "Snow / ice", "2": "Snow-free"},
                note="NDSI > 0.4 with NIR > 0.11 (Hall et al. 1995). A median composite smooths short snow events: for seasonal snow cover use a "
                     "narrow date window; late-summer (Aug-Sep) composites approximate perennial snow and glacier ice. Debris-covered ice is not "
                     "detected by NDSI. Shadowed snow in deep valleys may be missed; clouds left in the composite can be mistaken for snow.")


def _snowline(z, is_focus, w, fine_m=100.0, min_km2=0.5):
    """50 % crossing of the focus-class share on fine elevation bands (v1.4.6). Interpolating between the mid-points of coarse
    custom zones put the Astore snowline at 6 622 m, because the top zone 5500-8100 m has its mid-point at 6 800 m."""
    lo = np.floor(z.min() / fine_m) * fine_m
    idx = ((z - lo) // fine_m).astype(np.int64)
    area = np.bincount(idx, weights=w)
    foc = np.bincount(idx, weights=w * is_focus, minlength=len(area))
    ok = area >= min_km2
    mids = lo + (np.arange(len(area)) + 0.5) * fine_m
    share, mids = foc[ok] / area[ok], mids[ok]
    if share.size and share[0] >= 0.5:
        return float(mids[0]), fine_m
    for a in range(len(share) - 1):
        if share[a] < 0.5 <= share[a + 1]:
            return float(mids[a] + (0.5 - share[a]) / (share[a + 1] - share[a]) * (mids[a + 1] - mids[a])), fine_m
    return None, fine_m


def zone_statistics(store, dem, layer, band_m=500.0, zones=None, clip=None, labels=None, focus_class=None):
    """Area of each class of a categorical layer per elevation band / zone, with shares; snowline where focus class crosses 50 %."""
    d, c = store.get(dem), store.get(layer)
    if d.data.shape != c.data.shape:
        raise ValueError(f"{layer} and {dem} must share one grid (download the DEM with the map as template, or align them).")
    m = ~d.mask & ~c.mask & _clip_mask(d, clip)
    z = d.data.astype("float64")[m]
    k = c.data[m].astype(np.int64)
    w = np.broadcast_to(row_cell_area_m2(d)[:, None], d.data.shape)[m] / 1e6
    e = _edges(float(z.min()), float(z.max()), float(band_m), zones)
    zi = np.clip(np.searchsorted(e, z, side="right") - 1, 0, len(e) - 2)
    names = [f"{int(e[i])}-{int(round(e[i + 1]))} m" for i in range(len(e) - 1)]
    df = pd.DataFrame({"zone": np.array(names)[zi], "zi": zi, "cls": k, "w": w})
    piv = df.pivot_table(index=["zi", "zone"], columns="cls", values="w", aggfunc="sum", fill_value=0.0)
    piv.columns = [f"{cc} {(labels or {}).get(str(cc), '')}".strip() for cc in piv.columns]
    tot = piv.sum(axis=1)
    out = piv.copy()
    out.insert(0, "zone_area_km2", tot)
    for col in piv.columns:
        out[f"% {col}"] = piv[col] / tot * 100
    out = out.reset_index().drop(columns="zi")
    res = dict(dem=dem, layer=layer, clipped=clip is not None, zones=out.round(3).to_dict(orient="records"),
               class_totals_km2={col: float(piv[col].sum()) for col in piv.columns})
    if focus_class is not None:
        col = next((cc for cc in piv.columns if cc.split()[0] == str(int(focus_class))), None)
        if col is not None:
            zids = [i for i, _ in piv.index]
            share = (piv[col] / tot).to_numpy()
            sl, fine_m = _snowline(z, k == int(focus_class), w)
            res.update(focus_class=col, focus_share_by_zone=dict(zip(np.array(names)[zids], np.round(share * 100, 2).tolist())),
                       snowline_50pct_m=sl, snowline_band_m=fine_m,
                       note=f"Snowline = lowest elevation where the focus class covers half of the area, from {fine_m:.0f} m bands whatever the "
                            "zones shown (linear interpolation between band mid-points; bands under 0.5 km2 ignored); None if it never reaches 50 %.")
    return res
