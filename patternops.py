"""Store-level landscape-pattern and hotspot analyses (v0.7.0), shared by the Streamlit tab and the agent."""
import numpy as np
import pandas as pd
from rasterio.transform import Affine, xy
from rasterio.warp import transform as warp_transform

import hotspot
import landscape
from rasterops import _projected_metres
from store import to_geotiff_bytes

MAX_LISA_CELLS = 400_000


def _res(r):
    _projected_metres(r)
    a, e = abs(r.transform.a), abs(r.transform.e)
    if not np.isclose(a, e, rtol=1e-6):
        raise ValueError(f"{r.name} has non-square pixels ({a} x {e}); landscape metrics need square cells.")
    return a * (r.crs.linear_units_factor[1] if r.crs.linear_units_factor else 1.0)


def _categorical(r):
    v = r.data[~r.mask]
    if r.data.dtype.kind == "f" and v.size and not np.all(np.mod(v, 1) == 0):
        raise ValueError(f"{r.name} is not categorical (non-integer values).")
    return r.data.astype(np.int64)


def _jsonable(d):
    return {k: (None if isinstance(v, float) and not np.isfinite(v) else round(float(v), 4) if isinstance(v, (float, np.floating))
                else int(v) if isinstance(v, (np.integer,)) else v) for k, v in d.items()}


def landscape_metrics(store, layers, neighbourhood=8, edge_depth_m=None, labels=None, patches_top=0, nearest_neighbour=True):
    if isinstance(layers, str):
        layers = [layers]
    out, land_rows, class_frames = {}, [], []
    for name in layers:
        r = store.get(name)
        res = _res(r)
        depth = max(1, int(round((edge_depth_m or res) / res)))
        m = landscape.compute(_categorical(r), ~r.mask, res, int(neighbourhood), depth, labels, with_patches=patches_top > 0,
                              with_enn=bool(nearest_neighbour))
        land_rows.append(dict(layer=name, **m["landscape"]))
        class_frames.append(m["classes"].assign(layer=name))
        if patches_top:
            out.setdefault("largest_patches", {})[name] = m["patches"].nlargest(int(patches_top), "area_ha").round(4).to_dict(orient="records")
    land = pd.DataFrame(land_rows)
    cls = pd.concat(class_frames, ignore_index=True)
    out.update(layers=list(layers), neighbourhood=int(neighbourhood), edge_depth_cells=depth,
               landscape=[_jsonable(x) for x in land.to_dict(orient="records")],
               classes=[_jsonable(x) for x in cls.to_dict(orient="records")])
    if len(layers) > 1:
        num = land.drop(columns="layer")
        out["landscape_change_first_to_last"] = _jsonable((num.iloc[-1] - num.iloc[0]).to_dict())
    out["interpretation"] = ("Rising NP, PD and ED with falling LPI, MESH, AI and COHESION indicate fragmentation; rising CONTAG and AI "
                             "indicate aggregation; SHDI/SHEI measure composition diversity. Metrics depend on resolution, extent and the "
                             "class scheme: compare only maps with identical grid and legend.")
    return out


def moving_window_raster(store, layer, metric, window_m, out_name, class_code=None):
    r = store.get(layer)
    res = _res(r)
    arr, size = landscape.moving_window(_categorical(r), ~r.mask, res, metric, float(window_m), class_code)
    out = np.where(np.isfinite(arr), arr, -9999).astype("float32")
    store.outputs[out_name] = to_geotiff_bytes(r.profile, out, "float32", -9999)
    v = arr[np.isfinite(arr)]
    return dict(output=out_name, metric=metric.upper(), window_cells=size, window_m=size * res,
                min=float(v.min()) if v.size else None, mean=float(v.mean()) if v.size else None, max=float(v.max()) if v.size else None,
                note="Moving-window maps show where composition or configuration changes across the study area; the window size sets the scale.")


def _variable(store, layer, second_layer, variable, class_code):
    r = store.get(layer)
    if variable == "value":
        return r, r.data.astype(float), ~r.mask, f"value of {layer}"
    a = _categorical(r)
    if variable == "presence":
        if class_code is None:
            raise ValueError("presence needs class_code")
        return r, (a == int(class_code)) * 100.0, ~r.mask, f"% class {class_code} in {layer}"
    if not second_layer:
        raise ValueError(f"variable '{variable}' needs second_layer (the later map).")
    b_r = store.get(second_layer)
    if b_r.data.shape != r.data.shape:
        raise ValueError("Rasters differ in size; align them first.")
    b = _categorical(b_r)
    valid = ~(r.mask | b_r.mask)
    if variable == "change":
        x, lab = (a != b), f"% changed {layer}→{second_layer}"
    elif variable in ("gain", "loss"):
        if class_code is None:
            raise ValueError(f"{variable} needs class_code")
        c = int(class_code)
        x = ((a != c) & (b == c)) if variable == "gain" else ((a == c) & (b != c))
        lab = f"% {variable} of class {c} {layer}→{second_layer}"
    else:
        raise ValueError("variable must be value, presence, change, gain or loss")
    return r, x * 100.0, valid, lab


def _profile(r, shape, factor):
    p = dict(r.profile)
    t = r.transform
    p.update(height=shape[0], width=shape[1], transform=Affine(t.a * factor, t.b * factor, t.c, t.d * factor, t.e * factor, t.f))
    return p


def hotspot_analysis(store, layer, variable="value", second_layer=None, class_code=None, block=10, radius=1,
                     kernel_shape="square", method="both", fdr=True, permutations=199, output_prefix="hotspot"):
    r, x, valid, label = _variable(store, layer, second_layer, variable, class_code)
    block = max(1, int(block))
    g, gv = hotspot.aggregate(x, valid, block)
    n = int(gv.sum())
    if n < 30:
        raise ValueError(f"Only {n} valid cells after aggregation; reduce the block size.")
    k = hotspot.kernel(int(radius), kernel_shape)
    prof = _profile(r, g.shape, block)
    cell_m = abs(prof["transform"].a)
    cell_area_ha = abs(prof["transform"].a * prof["transform"].e) / 1e4 if r.crs is not None and r.crs.is_projected else None
    out = dict(variable=label, block_cells=block, analysis_cell_size=cell_m, grid=list(g.shape), valid_cells=n,
               neighbourhood=f"{kernel_shape} radius {int(radius)} cells ({int(k.sum()) - 1} neighbours)",
               global_moran=hotspot.global_moran(np.nan_to_num(g), gv, k), outputs=[])
    gz = np.nan_to_num(g)
    if method in ("gi", "both"):
        z, p, bins = hotspot.gi_star(gz, gv, k, fdr=fdr)
        zn, bn = f"{output_prefix}_gi_z.tif", f"{output_prefix}_gi_bins.tif"
        store.outputs[zn] = to_geotiff_bytes(prof, np.where(gv, z, -9999).astype("float32"), "float32", -9999)
        store.outputs[bn] = to_geotiff_bytes(prof, np.where(gv, bins, -128).astype("int16"), "int16", -128)
        out["outputs"] += [zn, bn]
        cnt = {hotspot.GI_NAMES[b]: int(((bins == b) & gv).sum()) for b in range(-3, 4)}
        out["gi_star"] = dict(fdr_corrected=bool(fdr), cells_by_bin=cnt,
                              area_ha_by_bin={k_: v * cell_area_ha for k_, v in cnt.items()} if cell_area_ha else None)
        # strongest hot and cold spots (cell centres)
        zz = np.where(gv, z, np.nan)
        spots = []
        for kind, idx in (("hot", np.argsort(-np.nan_to_num(zz, nan=-np.inf), axis=None)[:5]),
                          ("cold", np.argsort(np.nan_to_num(zz, nan=np.inf), axis=None)[:5])):
            rr, cc = np.unravel_index(idx, zz.shape)
            xs, ys = xy(prof["transform"], rr, cc, offset="center")
            lon, lat = (warp_transform(r.crs, "EPSG:4326", list(np.atleast_1d(xs)), list(np.atleast_1d(ys))) if r.crs else (xs, ys))
            for a_, b_, xx, yy, lo, la in zip(rr, cc, np.atleast_1d(xs), np.atleast_1d(ys), lon, lat):
                spots.append(dict(type=kind, z=round(float(zz[a_, b_]), 3), value=round(float(g[a_, b_]), 3), x=float(xx), y=float(yy),
                                  lon=round(float(lo), 6), lat=round(float(la), 6)))
        out["gi_star"]["strongest_spots"] = spots
    if method in ("lisa", "both"):
        if n > MAX_LISA_CELLS:
            out["lisa"] = dict(skipped=f"{n:,} cells exceed {MAX_LISA_CELLS:,}; increase the block size for LISA.")
        else:
            Ii, p, q, cl = hotspot.local_moran(gz, gv, k, int(permutations), 0.05, fdr=fdr)
            cn = f"{output_prefix}_lisa_clusters.tif"
            store.outputs[cn] = to_geotiff_bytes(prof, np.where(gv, cl, 255).astype("uint8"), "uint8", 255)
            out["outputs"].append(cn)
            out["lisa"] = dict(permutations=int(permutations), fdr_corrected=bool(fdr), legend=hotspot.CLUSTER_NAMES,
                               cells_by_cluster={hotspot.CLUSTER_NAMES[c]: int(((cl == c) & gv).sum()) for c in range(5)})
    out["note"] = ("Hotspots depend on the block size and neighbourhood (modifiable areal unit problem): test 2-3 settings and report them. "
                   "Gi* bins: ±3 = 99 %, ±2 = 95 %, ±1 = 90 % confidence" + (" after FDR correction." if fdr else "."))
    return out
