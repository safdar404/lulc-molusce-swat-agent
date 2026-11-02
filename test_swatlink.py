"""Tests for v1.0.0: SWAT+ land-use lookup, Curve Number runoff, RUSLE and streamflow evaluation."""
import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

import swatlink as W
from session import Session
from store import to_geotiff_bytes


def test_curve_number_hand_computed():
    assert W.runoff_mm(50, 80) == pytest.approx(37.3 ** 2 / 100.8, rel=1e-4)   # S = 63.5 mm, Ia = 12.7 mm
    assert W.runoff_mm(10, 80) == 0                                           # P < Ia
    assert W.runoff_mm(100, 100) == pytest.approx(100)
    assert W.cn_slope_adjust(np.array([80.0]), np.array([0.05]))[0] == pytest.approx(80, abs=1e-3)   # CN2 is defined at 5 % slope
    assert W.cn_slope_adjust(np.array([80.0]), np.array([0.30]))[0] > 80


def test_ls_and_d8():
    dem9 = np.add.outer(np.arange(20)[::-1] * 30 * 0.09, np.zeros(20))
    assert W.ls_factor(dem9, 30, "slope_length", 22.13)[10, 10] == pytest.approx(1.0, abs=0.01)   # unit plot: 22.13 m, 9 %
    plane = np.add.outer(np.arange(30)[::-1] * 1.0, np.zeros(10))
    acc = W.d8_accumulation(plane, 30)
    assert acc[-1, 5] == 30 and acc[0, 5] == 1


def test_fdc_signatures_and_ratings():
    q = np.random.default_rng(0).gamma(2, 10, 2000)
    s = W.fdc_signatures(q, q)
    assert all(abs(v) < 1e-9 for v in s.values())
    assert W.fdc_signatures(q, q * 1.1)["pbias_fhv"] == pytest.approx(10)
    assert (W.rate("nse", 0.85), W.rate("nse", 0.6), W.rate("nse", 0.3)) == ("very good", "satisfactory", "unsatisfactory")
    assert W.rate("pbias_percent", -7) == "good" and W.rate("rsr", 0.55) == "good"


def test_keywords():
    assert [W.suggest_code(n) for n in ["Built-up", "Water bodies", "Dense forest", "Cropland", "Barren land", "Shrubland", "Rice paddy"]] == \
        ["URMD", "WATR", "FRST", "AGRL", "BARR", "RNGB", "RICE"]


@pytest.fixture(scope="module")
def sess():
    H, Wd = 60, 80
    base = np.full((H, Wd), 2, "uint8")       # forest
    base[:, :20] = 3                           # cropland
    base[:10, :] = 1                           # water
    scen = base.copy()
    scen[30:, 40:] = 4                         # forest -> built-up
    hsg = np.full((H, Wd), 3, "uint8")
    hsg[:, 60:] = 2
    dem = np.add.outer(np.arange(H)[::-1] * 3.0, np.arange(Wd) * 0.5).astype("float32")
    s = Session()

    def prof(dt):
        return dict(driver="GTiff", height=H, width=Wd, count=1, dtype=dt, crs=CRS.from_epsg(32643), transform=from_origin(400000, 3500000, 30, 30))
    s.store.add("lulc_2020.tif", to_geotiff_bytes(prof("uint8"), base, "uint8", 0))
    s.store.add("sim_2040.tif", to_geotiff_bytes(prof("uint8"), scen, "uint8", 0))
    s.store.add("hsg.tif", to_geotiff_bytes(prof("uint8"), hsg, "uint8", 0))
    s.store.add("dem.tif", to_geotiff_bytes(prof("float32"), dem, "float32", -9999))
    days = pd.date_range("2000-01-01", "2004-12-31")
    rng = np.random.default_rng(1)
    rain = np.where(rng.random(days.size) < 0.25, rng.gamma(1.2, 15, days.size), 0)
    s.tables["rain.csv"] = pd.DataFrame({"date": days, "P": rain})
    obs = 5 + np.convolve(rain, np.exp(-np.arange(30) / 6), "full")[: days.size] * 0.2
    s.tables["q.csv"] = pd.DataFrame({"date": days, "obs": obs, "sim": obs * 0.93 + rng.normal(0, 0.8, days.size)})
    s.tables["runs.csv"] = pd.DataFrame({"date": days, "base": obs, "scen": obs * 1.12})
    return s


LABELS = {"1": "Water", "2": "Forest", "3": "Cropland", "4": "Built-up"}


def test_lookup(sess):
    r = sess.call("swat_landuse_lookup", {"layers": ["lulc_2020.tif", "sim_2040.tif"], "labels": LABELS})
    assert r["lookup"] == {"1": "WATR", "2": "FRST", "3": "AGRL", "4": "URMD"}
    assert r["lookup_csv"].splitlines()[0] == "LANDUSE_ID,SWAT_CODE" and "4,URMD" in r["lookup_csv"]
    assert "error" in sess.call("curve_number_runoff", {"layers": ["lulc_2020.tif"], "labels": {"1": "Water"}})   # unmapped classes


def test_cn_runoff_scenarios(sess):
    r = sess.call("curve_number_runoff", {"layers": ["lulc_2020.tif", "sim_2040.tif"], "labels": LABELS, "hsg_layer": "hsg.tif", "dem": "dem.tif",
                                          "storm_mm": 60, "rain_table": "rain.csv", "date_column": "date", "rain_column": "P"})
    assert "error" not in r, r
    a, b = r["results"]
    assert b["mean_CN"] > a["mean_CN"] and b["storm_runoff_mm"] > a["storm_runoff_mm"] and b["mean_annual_runoff_mm"] > a["mean_annual_runoff_mm"]
    assert b["change_storm_runoff_mm_pct_vs_first"] > 0
    cn = sess.store.get("lulc_2020_CN.tif")
    assert cn.data[5, 5] == pytest.approx(98, abs=0.5)        # water


def test_rusle(sess):
    for method in ("slope_length", "flow_accumulation"):
        r = sess.call("rusle_erosion", {"layers": ["lulc_2020.tif", "sim_2040.tif"], "dem": "dem.tif", "R": 600, "K": 0.03, "labels": LABELS,
                                        "ls_method": method})
        assert "error" not in r, r
        bc = {(x["layer"], x["swat_code"]): x["mean_t_ha_yr"] for x in r["by_class"]}
        assert bc[("lulc_2020.tif", "AGRL")] > bc[("lulc_2020.tif", "FRST")] > 0
        assert bc[("lulc_2020.tif", "WATR")] == 0
    assert "LS_factor.tif" in sess.store.names()


def test_flow_evaluation_and_attribution(sess):
    r = sess.call("flow_evaluation", {"observed_table": "q.csv", "simulated_table": "q.csv", "date_column": "date", "observed_column": "obs",
                                      "simulated_column": "sim", "split_date": "2003-01-01", "warmup_end": "2000-03-01"})
    assert "error" not in r, r
    assert {"calibration", "validation", "all"} <= set(r)
    assert r["all"]["pbias_percent"] == pytest.approx(7, abs=1) and r["all"]["ratings"]["pbias_percent"] == "good"
    assert r["calibration"]["n"] + r["validation"]["n"] == r["all"]["n"]
    m = sess.call("flow_evaluation", {"observed_table": "q.csv", "simulated_table": "q.csv", "date_column": "date", "observed_column": "obs",
                                      "simulated_column": "sim", "step": "monthly"})
    assert m["all"]["n"] == 60
    a = sess.call("lulc_flow_attribution", {"baseline_table": "runs.csv", "scenario_table": "runs.csv", "date_column": "date",
                                            "baseline_column": "base", "scenario_column": "scen"})
    assert a["mean_change_pct"] == pytest.approx(12) and a["Q95_change_pct"] == pytest.approx(12)
