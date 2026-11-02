"""Tests for v0.6.0: area-adjusted accuracy (Olofsson 2014 benchmark) and intensity analysis."""
import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

import changeops
import intensity
import olofsson
from session import Session
from store import to_geotiff_bytes

# ---------- Olofsson et al. (2014) worked example, RSE 148: 42-57 ----------
N = np.array([[66, 0, 5, 4], [0, 55, 8, 12], [1, 0, 153, 11], [2, 1, 9, 313]])
HA = np.array([200_000, 150_000, 3_200_000, 6_450_000]) * 0.09


def test_olofsson_benchmark():
    r = olofsson.olofsson_accuracy(N, HA)
    assert r.overall == pytest.approx(0.947, abs=1e-3)
    assert olofsson.Z95 * r.overall_se == pytest.approx(0.018, abs=1e-3)
    np.testing.assert_allclose(r.users, [0.88, 0.73, 0.93, 0.96], atol=0.005)
    np.testing.assert_allclose(r.producers, [0.75, 0.85, 0.93, 0.96], atol=0.006)
    np.testing.assert_allclose(r.area, [21_158, 11_686, 285_770, 581_386], rtol=1e-3)
    np.testing.assert_allclose(r.area_ci95, [6_158, 3_756, 15_510, 16_282], rtol=2e-3)
    p = r.pontius
    assert p["quantity"] + p["allocation"] == pytest.approx(1 - r.overall)
    assert p["exchange"] + p["shift"] == pytest.approx(p["allocation"])


def test_sample_size_matches_paper():
    d = olofsson.sample_size_design(HA, [0.7, 0.6, 0.9, 0.95], 0.01)
    assert d["n_total_formula"].iloc[0] == 641
    assert (d["n_samples"] >= 50).all()


# ---------- Intensity analysis, hand-computed ----------
def test_intensity_hand_computed():
    m = np.array([[60.0, 20.0], [10.0, 10.0]])  # rows = 2000, cols = 2010; extent 100
    res = intensity.intensity_analysis([m], [2000, 2010], ["A", "B"])
    iv = res.interval.iloc[0]
    assert iv.change_area == pytest.approx(30)
    assert iv.S_annual_pct == pytest.approx(3.0)            # 30/100/10 yr
    cat = res.category.set_index("category")
    assert cat.loc["B", "G_gain_intensity"] == pytest.approx(20 / 10 / 30 * 100)  # gain / end area
    assert cat.loc["A", "L_loss_intensity"] == pytest.approx(20 / 10 / 80 * 100)  # loss / start area
    assert cat.loc["B", "gain_status"] == "active" and cat.loc["A", "gain_status"] == "dormant"
    assert cat.loc["A", "swap"] == pytest.approx(20)        # 2*min(10, 20)


def test_intensity_uniform_is_weighted_mean_of_R():
    rng = np.random.default_rng(1)
    mats = [rng.random((4, 4)) * 100 for _ in range(2)]
    mats[1] = mats[1] / mats[1].sum() * mats[0].sum()
    res = intensity.intensity_analysis(mats, [2000, 2008, 2020])
    tg = res.transition_gain
    for (iv, to), g in tg.groupby(["interval", "to"]):
        t = 0 if iv.startswith("2000") else 1
        start = mats[t].sum(1)
        idx = [res.classes.index(c) for c in g["from"]]
        w = start[idx] / start[idx].sum()
        assert (g["R_intensity"] * w).sum() == pytest.approx(g["W_uniform"].iloc[0])


# ---------- store-level pipeline ----------
def _session(arrays, crs="EPSG:32643"):
    s = Session()
    for name, a in arrays.items():
        prof = dict(driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype="uint8", crs=CRS.from_string(crs),
                    transform=from_origin(500000, 4000000, 30, 30) if crs != "EPSG:4326" else from_origin(70, 1, 0.1, 0.1))
        s.store.add(name, to_geotiff_bytes(prof, a, "uint8", 0))
    return s


def test_store_pipeline_accuracy_and_points():
    rng = np.random.default_rng(0)
    a = rng.choice([1, 2, 3], size=(200, 200), p=[0.1, 0.3, 0.6]).astype("uint8")
    s = _session({"lulc_2020.tif": a})
    d = s.call("design_accuracy_sample", {"raster": "lulc_2020.tif"})
    assert "error" not in d and d["n_allocated"] > 0
    p = s.call("generate_sample_points", {"raster": "lulc_2020.tif", "n_per_class": {"1": 50, "2": 60, "3": 80}, "seed": 3})
    assert p["points"] == 190
    pts = s.tables["accuracy_points.csv"].copy()
    pts["reference_class"] = pts["map_class"]
    pts.loc[:9, "reference_class"] = 3  # inject some error
    s.tables["filled.csv"] = pts
    r = s.call("area_adjusted_accuracy", {"raster": "lulc_2020.tif", "table": "filled.csv", "reference_column": "reference_class",
                                          "x_column": "x", "y_column": "y"})
    assert "error" not in r, r
    assert 0.9 < r["overall_accuracy"] < 1.0 and r["points_used"] == 190
    total = sum(c["adjusted area (ha)"] for c in r["classes"])
    assert total == pytest.approx(200 * 200 * 0.09, rel=1e-6)


def test_store_pipeline_intensity_and_rasters():
    a = np.ones((50, 50), "uint8")
    b = a.copy()
    b[:10] = 2
    c = b.copy()
    c[:5] = 1  # alternation: 1 -> 2 -> 1 for rows 0-4
    s = _session({"lulc_2000.tif": a, "lulc_2010.tif": b, "lulc_2020.tif": c})
    r = s.call("intensity_analysis", {"layers": ["lulc_2020.tif", "lulc_2000.tif", "lulc_2010.tif"]})
    assert "error" not in r, r
    assert r["years"] == [2000, 2010, 2020]
    comp = {x["category"]: x for x in r["components"]}
    assert comp["1"]["alternation"] == pytest.approx(5 * 50 * 0.09)
    f = s.call("change_frequency_raster", {"layers": r["layers"], "output_name": "cf.tif"})
    assert f["pixels_by_number_of_changes"] == {0: 2000, 1: 250, 2: 250}
    t = s.call("trajectory_raster", {"layers": r["layers"], "category": 2, "output_name": "tr.tif"})
    assert t["area_by_trajectory"]["gain without alternation"] == pytest.approx(250 * 0.09)
    assert t["area_by_trajectory"]["alternation, gain first"] == pytest.approx(250 * 0.09)
    assert "cf.tif" in s.store.outputs and "tr.tif" in s.store.outputs


def test_geographic_area_and_grid_check():
    s = _session({"g.tif": np.ones((10, 10), "uint8")}, crs="EPSG:4326")
    areas, _ = changeops.class_area(s.store.get("g.tif"), "km2")
    assert areas[1] == pytest.approx(12_364, rel=0.01)
    s2 = _session({"a_2000.tif": np.ones((10, 10), "uint8"), "b_2010.tif": np.ones((12, 10), "uint8")})
    assert "error" in s2.call("intensity_analysis", {"layers": ["a_2000.tif", "b_2010.tif"]})


def test_points_with_lonlat():
    rng = np.random.default_rng(2)
    a = rng.choice([1, 2], size=(100, 100)).astype("uint8")
    s = _session({"m_2020.tif": a})
    pts = changeops.sample_points(s.store, "m_2020.tif", {1: 30, 2: 30})
    pts["reference_class"] = pts["map_class"]
    s.tables["ll.csv"] = pd.DataFrame(pts[["lon", "lat", "reference_class"]])
    r = s.call("area_adjusted_accuracy", {"raster": "m_2020.tif", "table": "ll.csv", "reference_column": "reference_class",
                                          "x_column": "lon", "y_column": "lat", "epsg": 4326})
    assert r["overall_accuracy"] == pytest.approx(1.0)
