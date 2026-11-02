"""Tests for v1.1.0: vector reading (zip / parts / GeoPackage / GeoJSON), rasterize, samples, zonal statistics, polygonize."""
import io
import os
import tempfile
import zipfile

import geopandas as gpd
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

import vectorops as V
from session import Session
from store import to_geotiff_bytes

T = from_origin(500000, 3500000, 30, 30)   # UTM 43N, 100 x 120 cells


def _session():
    lulc = np.ones((100, 120), "uint8")
    lulc[:, 60:] = 2
    lulc[70:, :] = 3
    s = Session()
    s.store.add("lulc.tif", to_geotiff_bytes(dict(driver="GTiff", height=100, width=120, count=1, dtype="uint8", crs=CRS.from_epsg(32643), transform=T),
                                             lulc, "uint8", 0))
    s.store.add("dem.tif", to_geotiff_bytes(dict(driver="GTiff", height=100, width=120, count=1, dtype="float32", crs=CRS.from_epsg(32643), transform=T),
                                            np.add.outer(np.arange(100.0), np.zeros(120)).astype("float32"), "float32", -9999))
    return s, lulc


def _zones():
    # two zones in UTM, delivered in WGS84 to test reprojection
    g = gpd.GeoDataFrame({"name": ["west", "east"], "landuse": ["Forest", "Urban"], "code": [1, 2]},
                         geometry=[box(500000, 3497000, 501800, 3500000), box(501800, 3497000, 503600, 3500000)], crs=32643)
    return g.to_crs(4326)


def _shp_bytes(g):
    with tempfile.TemporaryDirectory() as d:
        g.to_file(os.path.join(d, "zones.shp"))
        parts = {f: open(os.path.join(d, f), "rb").read() for f in os.listdir(d)}
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        for f, b in parts.items():
            z.writestr(f"folder/inner/{f}", b)
    return zb.getvalue(), parts


def test_read_formats():
    g = _zones()
    zipped, parts = _shp_bytes(g)
    with tempfile.TemporaryDirectory() as d:
        g.to_file(os.path.join(d, "z.gpkg"))
        gpkg = open(os.path.join(d, "z.gpkg"), "rb").read()
    out = V.read_vector({"zones.zip": zipped, "z.gpkg": gpkg, "z.geojson": g.to_json().encode()})
    assert set(out) == {"zones", "z"}  # z.gpkg and z.geojson share a stem; the later one wins
    assert all(len(v) == 2 for v in out.values())
    parts_named = {f"roads{os.path.splitext(f)[1]}": b for f, b in parts.items()}
    assert len(V.read_vector(parts_named)["roads"]) == 2
    with pytest.raises(ValueError):
        V.read_vector({"x.shp": parts["zones.shp"]})          # missing .shx/.dbf


def test_rasterize_and_zonal():
    s, lulc = _session()
    s.vectors["zones"] = _zones()
    r = s.call("rasterize_vector", {"vector": "zones", "template": "lulc.tif", "field": "landuse", "output_name": "zones.tif"})
    assert r["code_lookup"] == {"Forest": 1, "Urban": 2}
    z = s.store.get("zones.tif").data
    assert z[50, 10] == 1 and z[50, 100] == 2 and z[50, 59] == 1
    road = gpd.GeoDataFrame(geometry=[LineString([(500015, 3498500), (503585, 3498500)])], crs=32643)
    s.vectors["road"] = road
    rr = s.call("rasterize_vector", {"vector": "road", "template": "lulc.tif", "output_name": "road.tif", "all_touched": True})
    assert rr["burned_pixels"] >= 119
    zs = s.call("zonal_statistics", {"vector": "zones", "raster": "lulc.tif", "zone_field": "name", "labels": {"1": "crop", "2": "forest", "3": "urban"}})
    df = s.tables[zs["table"]].set_index("zone")
    assert zs["categorical"] and df.loc["west", "%1 crop"] == pytest.approx(70) and df.loc["east", "majority_class"] == 2
    assert df.loc["west", "area_ha"] == pytest.approx(60 * 100 * 0.09)
    zc = s.call("zonal_statistics", {"vector": "zones", "raster": "dem.tif"})
    assert not zc["categorical"] and s.tables[zc["table"]]["mean"].iloc[0] == pytest.approx(49.5)


def test_training_samples_points_and_polygonize():
    s, lulc = _session()
    s.vectors["zones"] = _zones()
    t = s.call("vector_training_samples", {"vector": "zones", "template": "lulc.tif", "class_field": "code", "max_per_class": 500})
    df = s.tables[t["table"]]
    assert t["per_class"] == {1: 500, 2: 500} and set(df["polygon_id"]) == {1, 2}
    pts = gpd.GeoDataFrame({"ref": [1, 2]}, geometry=[Point(500100, 3499900), Point(503000, 3499900)], crs=32643).to_crs(4326)
    s.vectors["gps"] = pts
    p = s.call("vector_points_to_table", {"vector": "gps", "template": "lulc.tif"})
    tb = s.tables[p["table"]]
    assert tb["x"].iloc[0] == pytest.approx(500100, abs=0.01)
    pz = s.call("polygonize_raster", {"layer": "lulc.tif"})
    g = s.vectors[pz["layer"]]
    assert pz["values"] == {1: 1, 2: 1, 3: 1}
    assert g.loc[g["value"] == 3, "area_ha"].sum() == pytest.approx(30 * 120 * 0.09)
    assert V.to_bytes(g, "gpkg")[:6] == b"SQLite" and b"FeatureCollection" in V.to_bytes(g, "geojson")
    assert "vectors" in s.call("list_session", {}) and "gps" in s.call("list_session", {})["vectors"]


def test_polygon_training_chain_into_classifier():
    from test_classify import S2, _scene
    s, truth = _scene()
    g = s.store.get("s2.tif")
    s.store.add("truth.tif", to_geotiff_bytes(dict(g.profile), truth, "uint8", 0))
    pz = s.call("polygonize_raster", {"layer": "truth.tif", "output_name": "truth_polys"})
    assert pz["features"] >= 4
    t = s.call("vector_training_samples", {"vector": "truth_polys", "template": "s2.tif", "class_field": "value", "max_per_class": 150})
    r = s.call("classify_image", {"table": t["table"], "class_column": "class", "x_column": "x", "y_column": "y", "stack": "s2.tif", "preset": S2,
                                  "n_trees": 40, "predict": False})
    assert "error" not in r, r
    assert "polygon_group_kfold" in r["cross_validation"] and r["cross_validation"]["polygon_group_kfold"]["overall_accuracy"] > 0.9
