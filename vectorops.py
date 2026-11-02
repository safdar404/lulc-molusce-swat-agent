"""Vector support (v1.1.0): read, describe, rasterize, sample, zonal statistics and polygonize.

Formats: zipped shapefile (any folder depth), shapefile parts uploaded together (.shp .shx .dbf .prj), GeoPackage, GeoJSON, KML, FlatGeobuf.
Archives and shapefile parts are unpacked into a private temporary folder that is deleted immediately after reading.
Every operation reprojects the vector to the raster's CRS, so vectors in WGS84 and rasters in UTM work together.
"""
import io
import os
import tempfile
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio import features
from rasterio.transform import xy

from store import to_geotiff_bytes

VECTOR_EXT = (".zip", ".gpkg", ".geojson", ".json", ".kml", ".fgb", ".shp", ".shx", ".dbf", ".prj", ".cpg")
_READABLE = (".shp", ".gpkg", ".geojson", ".json", ".kml", ".fgb")


def _read_dir(d):
    cands = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs if f.lower().endswith(_READABLE) and not f.startswith("._")]
    if not cands:
        raise ValueError("No .shp, .gpkg, .geojson, .kml or .fgb file found in the upload.")
    cands.sort(key=lambda p: _READABLE.index(os.path.splitext(p)[1].lower()))
    return gpd.read_file(cands[0])


def read_vector(files):
    """files: {filename: bytes}. Returns {layer_name: GeoDataFrame}."""
    out = {}
    parts = {}
    for name, raw in files.items():
        ext = os.path.splitext(name)[1].lower()
        stem = os.path.splitext(name)[0]
        if ext == ".zip":
            with tempfile.TemporaryDirectory() as d:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    for m in z.namelist():
                        if ".." in m or m.startswith("/"):
                            continue  # ignore unsafe paths
                        z.extract(m, d)
                out[stem] = _read_dir(d)
        elif ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            parts.setdefault(stem, {})[ext] = raw
        elif ext in (".geojson", ".json"):
            out[stem] = gpd.read_file(io.BytesIO(raw))
        elif ext in _READABLE:  # GeoPackage, KML, FlatGeobuf: read from a private temporary file with the right extension
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "layer" + ext)
                with open(p, "wb") as f:
                    f.write(raw)
                out[stem] = gpd.read_file(p)
        else:
            raise ValueError(f"{name}: unsupported vector format")
    for stem, p in parts.items():
        if not {".shp", ".shx", ".dbf"} <= set(p):
            raise ValueError(f"Shapefile {stem}: upload .shp, .shx and .dbf (and .prj) together, or zip them.")
        with tempfile.TemporaryDirectory() as d:
            for ext, raw in p.items():
                with open(os.path.join(d, "layer" + ext), "wb") as f:
                    f.write(raw)
            out[stem] = gpd.read_file(os.path.join(d, "layer.shp"))
    for k, g in out.items():
        if g.crs is None:
            raise ValueError(f"{k} has no coordinate reference system (.prj missing); add one in QGIS and upload again.")
        g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
        g["geometry"] = g.geometry.make_valid()
        out[k] = g
    return out


def describe(g, name):
    num = g.drop(columns="geometry").select_dtypes("number")
    cats = {}
    for c in g.drop(columns="geometry").columns.difference(num.columns)[:10]:
        vc = g[c].astype(str).value_counts()
        cats[c] = dict(unique=int(vc.size), top=vc.head(8).to_dict())
    return dict(layer=name, features=int(len(g)), crs=g.crs.to_string(), geometry_types=g.geom_type.value_counts().to_dict(),
                bounds=[round(float(v), 6) for v in g.total_bounds], fields={c: str(t) for c, t in g.drop(columns="geometry").dtypes.items()},
                numeric_summary=num.describe().T.round(4).to_dict(orient="index") if not num.empty else {}, categorical_summary=cats)


def _to_raster_crs(g, r):
    if r.crs is None:
        raise ValueError("Template raster has no CRS.")
    return g.to_crs(r.crs) if g.crs != r.crs else g


def _codes(series):
    """Numeric field -> as is (must be integers for categorical use); text field -> 1..n by sorted value."""
    if pd.api.types.is_numeric_dtype(series):
        return series.to_numpy(), None
    vals = sorted(series.dropna().astype(str).unique())
    lut = {v: i + 1 for i, v in enumerate(vals)}
    return series.astype(str).map(lut).to_numpy(), lut


def rasterize(g, r, field=None, burn=1, all_touched=False, dtype=None, nodata=None):
    """Burn a vector onto the grid of raster r. Returns (array, nodata, code_lookup)."""
    g = _to_raster_crs(g, r)
    lut = None
    if field:
        vals, lut = _codes(g[field])
    else:
        vals = np.full(len(g), burn)
    vals = np.asarray(vals, float)
    keep = np.isfinite(vals)
    is_int = np.all(np.mod(vals[keep], 1) == 0)
    dtype = dtype or ("int32" if is_int else "float32")
    nodata = (0 if (is_int and vals[keep].min(initial=1) > 0) else -9999) if nodata is None else nodata
    shapes = ((geom, v) for geom, v in zip(g.geometry[keep], vals[keep]))
    arr = features.rasterize(shapes, out_shape=r.data.shape, transform=r.transform, fill=nodata, all_touched=all_touched, dtype=dtype)
    return arr, nodata, lut


def training_from_polygons(g, r, class_field, max_per_class=2000, seed=42, all_touched=False):
    """Pixel centres inside polygons as training samples (x, y in raster CRS), with polygon_id for grouped validation."""
    g = _to_raster_crs(g, r).reset_index(drop=True)
    codes, lut = _codes(g[class_field])
    pid = features.rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)), out_shape=r.data.shape, transform=r.transform,
                             fill=0, all_touched=all_touched, dtype="int32")
    rr, cc = np.nonzero((pid > 0) & ~r.mask)
    ids = pid[rr, cc] - 1
    cls = np.asarray(codes)[ids]
    ok = np.isfinite(cls.astype(float))
    rr, cc, ids, cls = rr[ok], cc[ok], ids[ok], cls[ok].astype(int)
    rng = np.random.default_rng(seed)
    keep = []
    for c in np.unique(cls):
        idx = np.flatnonzero(cls == c)
        keep.append(idx if idx.size <= max_per_class else rng.choice(idx, max_per_class, replace=False))
    keep = np.concatenate(keep) if keep else np.array([], int)
    xs, ys = xy(r.transform, rr[keep], cc[keep], offset="center")
    df = pd.DataFrame({"x": np.atleast_1d(xs), "y": np.atleast_1d(ys), "class": cls[keep], "polygon_id": ids[keep] + 1})
    return df, lut


def points_to_table(g, r=None, crs=None):
    if not set(g.geom_type.unique()) <= {"Point", "MultiPoint"}:
        raise ValueError("Layer is not a point layer; use polygon sampling for polygons.")
    g = g.explode(index_parts=False)
    if r is not None:
        g = _to_raster_crs(g, r)
    elif crs:
        g = g.to_crs(crs)
    df = pd.DataFrame(g.drop(columns="geometry"))
    df["x"], df["y"] = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    return df


def zonal(g, r, zone_field=None, categorical=None, cat_labels=None):
    """Statistics of raster r inside each polygon. Categorical -> area (ha) and % per class; continuous -> mean, std, min, max."""
    g = _to_raster_crs(g, r).reset_index(drop=True)
    zid = features.rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)), out_shape=r.data.shape, transform=r.transform,
                             fill=0, dtype="int32")
    ok = (zid > 0) & ~r.mask
    z = zid[ok] - 1
    v = r.data[ok]
    if categorical is None:
        categorical = r.data.dtype.kind in "iu" and np.unique(v).size <= 60
    names = g[zone_field].astype(str).to_numpy() if zone_field else np.arange(1, len(g) + 1).astype(str)
    px = abs(r.transform.a * r.transform.e)
    proj = r.crs is not None and r.crs.is_projected
    if categorical:
        df = pd.crosstab(z, v.astype(np.int64))
        df = df.reindex(range(len(g)), fill_value=0)
        tot = df.sum(axis=1).replace(0, np.nan)
        out = pd.DataFrame({"zone": names, "pixels": df.sum(axis=1).to_numpy()})
        if proj:
            out["area_ha"] = out["pixels"] * px / 1e4
        for c in df.columns:
            lab = f"{c} {(cat_labels or {}).get(str(c), '')}".strip()
            out[f"%{lab}"] = (df[c] / tot * 100).round(3).to_numpy()
            if proj:
                out[f"ha_{lab}"] = (df[c] * px / 1e4).round(3).to_numpy()
        out["majority_class"] = df.idxmax(axis=1).where(tot.notna()).to_numpy()
    else:
        s = pd.DataFrame({"z": z, "v": v.astype(float)}).groupby("z")["v"].agg(["count", "mean", "std", "min", "max", "median"])
        s = s.reindex(range(len(g)))
        out = pd.concat([pd.DataFrame({"zone": names}), s.reset_index(drop=True)], axis=1)
    return out, bool(categorical)


def polygonize(r, mask_value=None, simplify=0.0, max_features=200_000):
    a = r.data
    m = ~r.mask if mask_value is None else (~r.mask & (a != mask_value))
    if a.dtype.kind == "f" and not np.all(np.mod(a[m], 1) == 0):
        raise ValueError("Polygonize needs a categorical (integer) raster.")
    arr = a.astype("int32")
    geoms, vals = [], []
    for geom, val in features.shapes(arr, mask=m, transform=r.transform, connectivity=8):
        geoms.append(geom)
        vals.append(int(val))
        if len(geoms) > max_features:
            raise ValueError(f"More than {max_features:,} polygons; apply a majority filter or aggregate first.")
    from shapely.geometry import shape
    g = gpd.GeoDataFrame({"value": vals}, geometry=[shape(x) for x in geoms], crs=r.crs)
    if simplify:
        g["geometry"] = g.geometry.simplify(simplify, preserve_topology=True)
    if r.crs is not None and r.crs.is_projected:
        g["area_ha"] = g.geometry.area / 1e4
    return g


def to_bytes(g, fmt="gpkg"):
    if fmt == "geojson":
        return g.to_crs(4326).to_json().encode()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.gpkg")
        g.to_file(p, driver="GPKG")
        with open(p, "rb") as f:
            return f.read()


def write_raster(store, r, arr, nodata, name):
    dtype = str(arr.dtype)
    store.outputs[name] = to_geotiff_bytes(r.profile, arr, dtype, nodata)
    return name
