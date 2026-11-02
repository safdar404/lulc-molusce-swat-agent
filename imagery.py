"""Imagery download (v1.3.0): cloud-free composites and base layers from the Microsoft Planetary Computer STAC API.

* Sentinel-2 L2A (10 bands, 10 m) and Landsat 4-9 Collection 2 Level-2 (6 bands, 30 m)
  - scene search by area, dates and cloud cover; least-cloudy scenes first
  - per-pixel cloud / shadow / cirrus masking (Sentinel-2 SCL classes 3, 8, 9, 10; Landsat QA_PIXEL bits 1-4)
  - conversion to surface reflectance (Sentinel-2 processing baseline >= 04.00 offset of -1000 DN; Landsat 2.75e-5 x DN - 0.2)
  - median composite on one target grid (UTM zone of the area, or the grid of a loaded raster), stored as reflectance x 10 000 (uint16)
  - a valid-observation count raster
* Copernicus DEM GLO-30 and ESA WorldCover 10 m (2020 / 2021) on the same grid

Only bounding-box windows are read from the cloud-optimised GeoTIFFs, never whole scenes.
"""
import datetime
import math
import os

import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds


STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{}"
MAX_PIXELS = 4_000_000          # per band on the target grid (memory guard for 1 GB hosts)
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff", GDAL_HTTP_MULTIRANGE="YES",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1", VSI_CACHE="TRUE")

PRODUCTS = {
    "Sentinel-2 L2A": dict(collection="sentinel-2-l2a", res=10,
                           bands=["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"],
                           names=["blue", "green", "red", "rededge1", "rededge2", "rededge3", "nir", "nir08", "swir16", "swir22"],
                           qa="SCL", preset="Sentinel-2 L2A, 10 bands (B2 B3 B4 B5 B6 B7 B8 B8A B11 B12)"),
    "Landsat 4-9 C2 L2": dict(collection="landsat-c2-l2", res=30, bands=["blue", "green", "red", "nir08", "swir16", "swir22"],
                              names=["blue", "green", "red", "nir", "swir1", "swir2"], qa="qa_pixel",
                              preset="Downloaded Landsat composite, 6 bands (blue green red nir swir1 swir2)"),
}
WORLDCOVER = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
              80: "Permanent water bodies", 90: "Herbaceous wetland", 95: "Mangroves", 100: "Moss and lichen"}


# ------------------------------------------------------------------ STAC
def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Client:
    """Thin STAC + SAS client (requests only). Tests pass a fake with the same two methods."""

    def __init__(self, session=None, timeout=60):
        self.http = session or requests.Session()
        self.timeout = timeout
        self._tokens = {}

    def search(self, collection, bbox, start, end, max_cloud=None, limit=200, query=None):
        body = dict(collections=[collection], bbox=list(bbox), datetime=f"{start}T00:00:00Z/{end}T23:59:59Z", limit=limit)
        q = dict(query or {})
        if max_cloud is not None:
            q["eo:cloud_cover"] = {"lt": float(max_cloud)}
        if q:
            body["query"] = q
        items, url = [], f"{STAC}/search"
        while url and len(items) < limit:
            r = self.http.post(url, json=body, timeout=self.timeout)
            r.raise_for_status()
            js = r.json()
            items += js.get("features", [])
            nxt = next((lk for lk in js.get("links", []) if lk.get("rel") == "next"), None)
            if not nxt:
                break
            url, body = nxt["href"], nxt.get("body", body)
        return items[:limit]

    def sign(self, collection, href):
        tok = self._tokens.get(collection)
        if tok is None or tok[1] < _utcnow() + datetime.timedelta(minutes=5):
            r = self.http.get(SAS.format(collection), timeout=self.timeout)
            r.raise_for_status()
            js = r.json()
            exp = datetime.datetime.strptime(js["msft:expiry"][:19], "%Y-%m-%dT%H:%M:%S") if "msft:expiry" in js else _utcnow() + datetime.timedelta(minutes=45)
            tok = (js["token"], exp)
            self._tokens[collection] = tok
        return href + ("&" if "?" in href else "?") + tok[0]


# ------------------------------------------------------------------ grids
def utm_epsg(lon, lat):
    zone = int(math.floor((lon + 180) / 6) + 1)
    return (32600 if lat >= 0 else 32700) + zone


def bbox_from_center(lon, lat, width_km, height_km=None):
    height_km = height_km or width_km
    dlat = height_km / 2 / 110.574
    dlon = width_km / 2 / (111.320 * math.cos(math.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def target_grid(bbox, res, template=None):
    """(crs, transform, (rows, cols)) for a lon/lat bbox, or the grid of a template raster."""
    if template is not None:
        return template.crs, template.transform, template.data.shape
    crs = CRS.from_epsg(utm_epsg((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
    x0, y1 = math.floor(x0 / res) * res, math.ceil(y1 / res) * res
    cols, rows = int(math.ceil((x1 - x0) / res)), int(math.ceil((y1 - y0) / res))
    return crs, from_origin(x0, y1, res, res), (rows, cols)


def grid_bbox_lonlat(crs, transform, shape):
    x0, y1 = transform.c, transform.f
    x1, y0 = x0 + transform.a * shape[1], y1 + transform.e * shape[0]
    return transform_bounds(crs, "EPSG:4326", min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), densify_pts=21)


def _read(href, crs, transform, shape, resampling, dtype="float32"):
    with rasterio.Env(**GDAL_ENV), rasterio.open(href) as src:
        with WarpedVRT(src, crs=crs, transform=transform, width=shape[1], height=shape[0], resampling=resampling,
                       src_nodata=src.nodata, nodata=src.nodata if src.nodata is not None else 0) as vrt:
            a = vrt.read(1, out_dtype=dtype)
            m = vrt.read_masks(1) == 0
    return a, m


# ------------------------------------------------------------------ masks and scaling
def s2_clear(scl):
    """Valid, cloud-free Sentinel-2 pixels: drop no-data (0), saturated (1), shadow (3), cloud medium/high (8, 9), cirrus (10)."""
    return ~np.isin(scl, [0, 1, 3, 8, 9, 10])


def landsat_clear(qa):
    """Landsat QA_PIXEL: fill (bit 0), dilated cloud (1), cirrus (2), cloud (3), cloud shadow (4) must all be 0."""
    qa = qa.astype(np.uint16)
    return (qa & 0b11111) == 0


def s2_offset(item):
    """Processing baseline >= 04.00 (from 25 Jan 2022) adds 1000 to L2A DN (BOA_ADD_OFFSET)."""
    pb = item.get("properties", {}).get("s2:processing_baseline")
    try:
        return -1000.0 if float(pb) >= 4.0 else 0.0
    except (TypeError, ValueError):
        dt = item.get("properties", {}).get("datetime", "")[:10]
        return -1000.0 if dt >= "2022-01-25" else 0.0


def to_reflectance(product, dn, item):
    if product == "Sentinel-2 L2A":
        return (dn + s2_offset(item)) / 10000.0
    return dn * 2.75e-5 - 0.2


# ------------------------------------------------------------------ main operations
def search_scenes(client, product, bbox, start, end, max_cloud=30, platforms=None):
    p = PRODUCTS[product]
    q = {"platform": {"in": platforms}} if platforms else None
    items = client.search(p["collection"], bbox, start, end, max_cloud, query=q)
    rows = []
    for it in items:
        pr = it.get("properties", {})
        rows.append(dict(id=it["id"], date=pr.get("datetime", "")[:10], cloud=round(float(pr.get("eo:cloud_cover", np.nan)), 2),
                         platform=pr.get("platform", ""), tile=pr.get("s2:mgrs_tile") or f"{pr.get('landsat:wrs_path', '')}/{pr.get('landsat:wrs_row', '')}"))
    order = np.argsort([r["cloud"] for r in rows], kind="stable")
    return [items[i] for i in order], [rows[i] for i in order]


def composite(client, product, items, crs, transform, shape, progress=None, statistic="median"):
    """Cloud-masked composite. Returns (uint16 cube reflectance x 10 000, observation count, used scene ids)."""
    if shape[0] * shape[1] > MAX_PIXELS:
        raise ValueError(f"Area is {shape[0]}x{shape[1]} = {shape[0] * shape[1]:,} pixels per band; the limit is {MAX_PIXELS:,}. "
                         "Use a smaller area or a coarser resolution.")
    p = PRODUCTS[product]
    col = p["collection"]
    masks, used = [], []
    n_steps = len(items) * (len(p["bands"]) + 1)
    step = 0
    for it in items:
        if p["qa"] not in it.get("assets", {}):
            continue
        qa, nod = _read(client.sign(col, it["assets"][p["qa"]]["href"]), crs, transform, shape, Resampling.nearest, "uint16")
        clear = (s2_clear(qa) if product == "Sentinel-2 L2A" else landsat_clear(qa)) & ~nod
        step += 1
        if progress:
            progress(step / n_steps, f"mask {it['id']}: {100 * clear.mean():.0f}% clear")
        if clear.any():
            masks.append(clear)
            used.append(it)
    if not used:
        raise ValueError("No cloud-free pixels in the selected scenes; widen the dates or raise the cloud limit.")
    count = np.sum(masks, axis=0).astype("uint8")
    cube = np.zeros((len(p["bands"]),) + tuple(shape), "uint16")
    for b, band in enumerate(p["bands"]):
        stack = np.full((len(used),) + tuple(shape), np.nan, "float32")
        for k, (it, m) in enumerate(zip(used, masks)):
            if band in it["assets"]:
                dn, nod = _read(client.sign(col, it["assets"][band]["href"]), crs, transform, shape, Resampling.bilinear)
                refl = to_reflectance(product, dn, it).astype("float32")
                stack[k] = np.where(m & ~nod & (dn > 0), refl, np.nan)
            step += 1
            if progress:
                progress(min(step / n_steps, 1.0), f"{band} · {it['id']}")
        with np.errstate(all="ignore"):
            agg = np.nanmedian(stack, axis=0) if statistic == "median" else np.nanmean(stack, axis=0)
        cube[b] = np.where(np.isfinite(agg), np.clip(np.round(agg * 10000), 1, 65534), 0).astype("uint16")
    return cube, count, [it["id"] for it in used]


def stack_bytes(cube, crs, transform, names, nodata=0):
    from rasterio.io import MemoryFile
    prof = dict(driver="GTiff", height=cube.shape[1], width=cube.shape[2], count=cube.shape[0], dtype=str(cube.dtype), crs=crs, transform=transform,
                nodata=nodata, compress="deflate", tiled=True, blockxsize=256, blockysize=256, interleave="band")
    with MemoryFile() as mf:
        with mf.open(**prof) as dst:
            dst.write(cube)
            for i, n in enumerate(names, 1):
                dst.set_band_description(i, n)
        return mf.read()


def single_asset(client, collection, asset, bbox, crs, transform, shape, resampling, dtype, start=None, end=None, pick="latest"):
    """Mosaic one asset (DEM, WorldCover) of all items covering the bbox onto the grid."""
    s, e = start or "2000-01-01", end or datetime.date.today().isoformat()
    items = client.search(collection, bbox, s, e, None)
    if not items:
        raise ValueError(f"No {collection} data for this area.")
    if pick == "latest":
        items = sorted(items, key=lambda it: it.get("properties", {}).get("datetime") or it.get("properties", {}).get("start_datetime") or "", reverse=True)
    out = np.zeros(shape, dtype)
    filled = np.zeros(shape, bool)
    for it in items:
        if asset not in it.get("assets", {}):
            continue
        a, nod = _read(client.sign(collection, it["assets"][asset]["href"]), crs, transform, shape, resampling, dtype)
        new = ~nod & ~filled
        out[new] = a[new]
        filled |= ~nod
        if filled.all():
            break
    return out, filled, [it["id"] for it in items]


def download_composite(store, client, product, bbox=None, start=None, end=None, max_cloud=30, n_scenes=6, res=None, template=None,
                       output_name=None, progress=None, statistic="median", platforms=None):
    p = PRODUCTS[product]
    tpl = store.get(template) if template else None
    if tpl is not None:
        bbox = grid_bbox_lonlat(tpl.crs, tpl.transform, tpl.data.shape)
    if bbox is None:
        raise ValueError("Give a bounding box (lon/lat) or a template raster.")
    crs, transform, shape = target_grid(bbox, float(res or p["res"]), tpl)
    items, rows = search_scenes(client, product, bbox, start, end, max_cloud, platforms)
    if not items:
        raise ValueError("No scenes found: widen the dates, raise the cloud limit or check the area.")
    sel = items[: int(n_scenes)]
    cube, count, used = composite(client, product, sel, crs, transform, shape, progress, statistic)
    name = output_name or f"{'S2' if product.startswith('Sentinel') else 'Landsat'}_{start[:4]}_{end[:4]}_composite.tif"
    store.outputs[name] = stack_bytes(cube, crs, transform, p["names"])
    cname = name.rsplit(".", 1)[0] + "_obs_count.tif"
    store.outputs[cname] = stack_bytes(count[None], crs, transform, ["valid observations"], nodata=255)
    covered = count > 0
    return dict(output=name, observation_count=cname, product=product, preset=p["preset"], crs=crs.to_string(), resolution_m=abs(transform.a),
                size=[int(shape[1]), int(shape[0])], bbox_lonlat=[round(v, 5) for v in bbox], scenes_found=len(items), scenes_used=used,
                scenes_table=rows[:50], pixels_with_data_pct=float(covered.mean() * 100), mean_observations=float(count[covered].mean()) if covered.any() else 0,
                note="Stored as surface reflectance x 10 000 (uint16, 0 = no data). In the Classification tab choose this file and the preset "
                     f"'{p['preset']}'. Pixels with 0 observations were cloudy in every scene: add scenes or widen the dates.")


def download_dem(store, client, bbox=None, template=None, res=30, output_name="copernicus_dem_30m.tif"):
    tpl = store.get(template) if template else None
    if tpl is not None:
        bbox = grid_bbox_lonlat(tpl.crs, tpl.transform, tpl.data.shape)
    crs, transform, shape = target_grid(bbox, float(res), tpl)
    if shape[0] * shape[1] > MAX_PIXELS * 4:
        raise ValueError("Area too large for the DEM download at this resolution.")
    dem, ok, ids = single_asset(client, "cop-dem-glo-30", "data", bbox, crs, transform, shape, Resampling.bilinear, "float32", "2021-01-01", "2022-12-31")
    arr = np.where(ok, dem, -9999).astype("float32")
    store.outputs[output_name] = stack_bytes(arr[None], crs, transform, ["elevation_m"], nodata=-9999)
    v = arr[ok]
    return dict(output=output_name, tiles=ids, crs=crs.to_string(), resolution_m=abs(transform.a), size=[int(shape[1]), int(shape[0])],
                min_m=float(v.min()) if v.size else None, max_m=float(v.max()) if v.size else None, coverage_pct=float(ok.mean() * 100),
                note="Copernicus DEM GLO-30 (ESA / Airbus), a digital surface model: elevations include buildings and canopy.")


def download_worldcover(store, client, bbox=None, template=None, res=10, year=2021, output_name=None):
    tpl = store.get(template) if template else None
    if tpl is not None:
        bbox = grid_bbox_lonlat(tpl.crs, tpl.transform, tpl.data.shape)
    crs, transform, shape = target_grid(bbox, float(res), tpl)
    if shape[0] * shape[1] > MAX_PIXELS * 4:
        raise ValueError("Area too large for WorldCover at this resolution.")
    wc, ok, ids = single_asset(client, "esa-worldcover", "map", bbox, crs, transform, shape, Resampling.nearest, "uint8",
                               f"{int(year)}-01-01", f"{int(year)}-12-31")
    arr = np.where(ok, wc, 0).astype("uint8")
    name = output_name or f"ESA_WorldCover_{int(year)}.tif"
    store.outputs[name] = stack_bytes(arr[None], crs, transform, ["land_cover"], nodata=0)
    u, c = np.unique(arr[ok], return_counts=True)
    pa = abs(transform.a * transform.e) / 1e4
    return dict(output=name, year=int(year), tiles=ids, crs=crs.to_string(), resolution_m=abs(transform.a), labels={str(k): v for k, v in WORLDCOVER.items()},
                class_area_ha={f"{int(k)} {WORLDCOVER.get(int(k), '')}".strip(): round(float(n) * pa, 2) for k, n in zip(u, c) if k},
                note="ESA WorldCover 10 m (Zanaga et al. 2021/2022), overall accuracy about 75-77%. Use it as a reference or a source of training "
                     "samples, not as ground truth.")


def offline_env():
    """True when the host cannot reach the Planetary Computer (used by the UI to explain failures)."""
    return os.environ.get("LULC_OFFLINE") == "1"
