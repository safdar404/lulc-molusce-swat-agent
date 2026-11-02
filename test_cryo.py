"""Tests for v1.4.0: KMZ upload, basin clipping, hypsometry, snow / ice mapping and elevation-zone statistics."""
import io
import os
import tempfile
import zipfile

import geopandas as gpd
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

import report
import vectorops as V
from session import Session
from store import to_geotiff_bytes

T = from_origin(500000, 3900000, 100, 100)          # 100 m grid, 200 x 150 cells = 20 x 15 km
H, W = 200, 150


def _prof(dt, count=1):
    return dict(driver="GTiff", height=H, width=W, count=count, dtype=dt, crs=CRS.from_epsg(32643), transform=T)


def _session():
    s = Session()
    dem = np.add.outer(np.linspace(6000, 2000, H), np.zeros(W)).astype("float32")      # uniform 2000-6000 m ramp, north high
    s.store.add("dem.tif", to_geotiff_bytes(_prof("float32"), dem, "float32", -9999))
    # 6-band "Landsat composite" (reflectance x 10000): snow above 4500 m, vegetation below
    snow = dem > 4500
    refl = {"blue": (0.60, 0.04), "green": (0.62, 0.07), "red": (0.60, 0.05), "nir": (0.55, 0.35), "swir1": (0.08, 0.20), "swir2": (0.05, 0.10)}
    cube = np.stack([np.where(snow, a, b) for a, b in refl.values()]) * 10000
    from rasterio.io import MemoryFile
    with MemoryFile() as mf:
        with mf.open(**_prof("uint16", 6), nodata=0) as d:
            d.write(cube.astype("uint16"))
        s.store.add("landsat.tif", mf.read())
    wc = np.where(snow, 70, 10).astype("uint8")
    wc[150:160, 20:40] = 80                          # a lake
    s.store.add("wc.tif", to_geotiff_bytes(_prof("uint8"), wc, "uint8", 0))
    basin = gpd.GeoDataFrame({"Name": ["basin"]}, geometry=[box(500000, 3900000 - 100 * H, 500000 + 100 * W / 2, 3900000)], crs=32643)  # west half
    s.vectors["basin"] = basin.to_crs(4326)
    return s, dem


def test_kmz_with_arcgis_attribute_table():
    g = gpd.GeoDataFrame({"Name": ["2"], "description": ["<html><table><tr><td colspan='2'>Pakistan</td></tr><tr><td>NAME_3</td><td>Astore</td></tr>"
                                                          "<tr><td>F_AREA</td><td>3988056412.5</td></tr></table></html>"]},
                         geometry=[box(74.4, 34.8, 75.2, 35.6)], crs=4326)
    with tempfile.TemporaryDirectory() as d:
        g.to_file(os.path.join(d, "doc.kml"), driver="KML")
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as z:
            z.write(os.path.join(d, "doc.kml"), "doc.kml")
            z.writestr("style.xsl", "<xsl/>")
    out = V.read_vector({"area_astore.kmz": zb.getvalue()})
    a = out["area_astore"]
    assert len(a) == 1 and a["NAME_3"].iloc[0] == "Astore" and a["F_AREA"].iloc[0] == pytest.approx(3988056412.5)
    assert "description" not in a.columns


def test_hypsometry_uniform_ramp():
    s, dem = _session()
    h = s.call("hypsometry", {"dem": "dem.tif", "band_m": 500})
    assert h["area_km2"] == pytest.approx(H * W * 0.01) and h["min_m"] == pytest.approx(2000) and h["max_m"] == pytest.approx(6000)
    assert h["hypsometric_integral"] == pytest.approx(0.5, abs=0.01)
    areas = [b["area_km2"] for b in h["bands"]]
    assert len(areas) == 8 and max(areas) - min(areas) < 0.6          # uniform ramp -> equal band areas
    z = s.call("hypsometry", {"dem": "dem.tif", "zones": [2500, 3500, 4500, 5500]})
    assert [b["from_m"] for b in z["bands"]] == [2000, 2500, 3500, 4500, 5500]
    c = s.call("hypsometry", {"dem": "dem.tif", "clip_vector": "basin"})
    assert c["area_km2"] == pytest.approx(H * W * 0.01 / 2, rel=0.01) and c["clipped"]


def test_snow_map_and_zone_statistics():
    s, dem = _session()
    r = s.call("map_snow_cover", {"stack": "landsat.tif", "preset": "Downloaded Landsat composite, 6 bands (blue green red nir swir1 swir2)",
                                  "water_layer": "wc.tif", "output_name": "snow.tif"})
    assert "error" not in r, r
    true_snow = (dem > 4500).sum() * 0.01
    assert r["snow_ice_km2"] == pytest.approx(true_snow, rel=0.01)
    z = s.call("elevation_zone_statistics", {"dem": "dem.tif", "layer": "snow.tif", "band_m": 500, "labels": r["labels"], "focus_class": 1})
    assert z["snowline_50pct_m"] == pytest.approx(4500, abs=260)
    assert z["class_totals_km2"]["1 Snow / ice"] == pytest.approx(true_snow, rel=0.01)
    assert z["snowline_50pct_m"] == pytest.approx(4500, abs=60) and z["snowline_band_m"] == 100
    # v1.4.6: coarse custom zones must not move the snowline (Astore: 6 622 m from the 5500-8100 m zone mid-point)
    zz = s.call("elevation_zone_statistics", {"dem": "dem.tif", "layer": "snow.tif", "zones": [2500, 3500, 5500], "labels": r["labels"],
                                              "focus_class": 1})
    assert zz["snowline_50pct_m"] == pytest.approx(4500, abs=60)
    zc = s.call("elevation_zone_statistics", {"dem": "dem.tif", "layer": "wc.tif", "zones": [3000, 4500], "clip_vector": "basin"})
    assert sum(zz["zone_area_km2"] for zz in zc["zones"]) == pytest.approx(H * W * 0.01 / 2, rel=0.01)
    blocks = report.build(s, {"title": "t"})
    assert any(b[0] == "h1" and b[1] == "Basin topography, snow and ice" for b in blocks)


def test_ndsi_index_and_snow_errors():
    import classify
    assert "NDSI" in classify.available_indices({"green": 1, "swir1": 1})
    s, _ = _session()
    assert "error" in s.call("map_snow_cover", {"band_map": {"green": "landsat.tif#2"}})


def test_imagery_clip_with_fake_client(tmp_path_factory):
    import imagery as I
    from test_imagery import LAT, LON, world
    client, _ = world.__wrapped__(tmp_path_factory) if hasattr(world, "__wrapped__") else (None, None)
    if client is None:
        pytest.skip("fixture helper unavailable")
    s = Session()
    bb = I.bbox_from_center(LON, LAT, 3)
    half = gpd.GeoDataFrame(geometry=[box(bb[0], bb[1], (bb[0] + bb[2]) / 2, bb[3])], crs=4326)
    s.vectors["half"] = half
    s.img_client = client
    r = s.call("download_composite", {"product": "Sentinel-2 L2A", "start": "2023-01-01", "end": "2023-12-31", "vector": "half", "clip_vector": "half",
                                      "n_scenes": 2, "output_name": "c.tif"})
    assert "error" not in r, r
    assert r["clipped"] and r["area_km2"] == pytest.approx(half.to_crs(32643).area.iloc[0] / 1e6, rel=0.05)
