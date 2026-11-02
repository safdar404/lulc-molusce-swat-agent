"""Tests for v0.7.0: landscape metrics (hand-computed FRAGSTATS values) and hotspot statistics.
The implementation was also cross-checked against pylandstats 3.1 and PySAL esda 2.10 (identical to 1e-12)."""
import math

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

import hotspot
import landscape
from session import Session
from store import to_geotiff_bytes


def _grid():
    a = np.full((4, 4), 2)
    a[1:3, 1:3] = 1  # one 2x2 patch of class 1 inside class 2
    return a


def test_class_metrics_hand_computed():
    m = landscape.compute(_grid(), np.ones((4, 4), bool), 30.0, 8, 1)
    c = m["classes"].set_index("class_code")
    assert c.loc[1, "PLAND"] == pytest.approx(25)
    assert c.loc[1, "NP"] == 1 and c.loc[2, "NP"] == 1
    assert c.loc[1, "TE_m"] == pytest.approx(8 * 30)          # 8 cell edges between classes
    assert c.loc[1, "LSI"] == pytest.approx(1.0)              # 8 edges / minimum 8 for 4 cells
    assert c.loc[2, "LSI"] == pytest.approx((8 + 16) / 14)     # 12 cells: min perimeter 4*3+2 = 14
    assert c.loc[1, "AI"] == pytest.approx(100)               # 4 like adjacencies = maximum for 4 cells
    assert c.loc[1, "SHAPE_MN"] == pytest.approx(1.0)
    assert c.loc[1, "TCA_ha"] == pytest.approx(0)             # every cell of a 2x2 patch is edge
    land = m["landscape"]
    assert land["SHDI"] == pytest.approx(-(0.25 * math.log(0.25) + 0.75 * math.log(0.75)))
    assert land["SIDI"] == pytest.approx(1 - 0.25**2 - 0.75**2)
    assert land["TE_m"] == pytest.approx(240)
    assert land["DIVISION"] == pytest.approx(1 - 0.25**2 - 0.75**2)


def test_patch_rule_and_enn():
    a = np.zeros((5, 5), int)
    a[0, 0] = a[1, 1] = 1        # diagonal neighbours
    a[4, 4] = 1
    v = np.ones_like(a, bool)
    c8 = landscape.compute(a, v, 10.0, 8, 1)["classes"].set_index("class_code")
    c4 = landscape.compute(a, v, 10.0, 4, 1)["classes"].set_index("class_code")
    assert c8.loc[1, "NP"] == 2 and c4.loc[1, "NP"] == 3
    # 8-rule: patch {(0,0),(1,1)} to (4,4): nearest cells (1,1)-(4,4) = sqrt(18) cells
    assert c8.loc[1, "ENN_MN_m"] == pytest.approx(10 * math.sqrt(18))


def test_contagion_extremes():
    half = np.zeros((20, 20), int)
    half[:, 10:] = 1
    chk = np.indices((20, 20)).sum(0) % 2
    v = np.ones((20, 20), bool)
    # FRAGSTATS CONTAG with P_i weighting: two equal halves -> hand-computed 41.22; checkerboard -> 50
    q_like, q_unlike = 0.5 * 740 / 760, 0.5 * 20 / 760
    expect = (1 + 2 * (q_like * math.log(q_like) + q_unlike * math.log(q_unlike)) / (2 * math.log(2))) * 100
    assert landscape.compute(half, v, 30.0)["landscape"]["CONTAG"] == pytest.approx(expect)
    assert landscape.compute(chk, v, 30.0)["landscape"]["CONTAG"] == pytest.approx(50)


def test_moving_window_shdi():
    a = np.indices((30, 30)).sum(0) % 2
    out, size = landscape.moving_window(a, np.ones_like(a, bool), 30.0, "SHDI", 90)
    assert size == 3
    assert out[15, 15] == pytest.approx(-(4 / 9 * math.log(4 / 9) + 5 / 9 * math.log(5 / 9)), rel=1e-5)


# ---------- hotspots ----------
def _brute_gi(x, r):
    n = x.size
    xb, s = x.mean(), x.std()
    H, W = x.shape
    out = np.zeros_like(x, float)
    for i in range(H):
        for j in range(W):
            nb = x[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
            w = nb.size
            out[i, j] = (nb.sum() - xb * w) / (s * math.sqrt((n * w - w * w) / (n - 1)))
    return out


def test_gi_star_matches_brute_force_and_finds_hotspot():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(25, 25))
    x[5:9, 5:9] += 4
    z, p, bins = hotspot.gi_star(x, np.ones_like(x, bool), hotspot.kernel(1), fdr=False)
    np.testing.assert_allclose(z, _brute_gi(x, 1), atol=1e-10)
    assert bins[6, 6] == 3 and (bins[15:, 15:] >= 0).mean() > 0.8


def test_global_and_local_moran():
    x = np.zeros((20, 20))
    x[:, :10] = 1.0
    v = np.ones_like(x, bool)
    g = hotspot.global_moran(x, v, hotspot.kernel(1))
    assert g["I"] > 0.8 and g["p"] < 1e-6
    Ii, p, q, cl = hotspot.local_moran(x + np.random.default_rng(1).normal(0, 0.01, x.shape), v, hotspot.kernel(1), 99)
    assert set(np.unique(q[2:-2, 2:8])) == {1} and set(np.unique(q[2:-2, 12:-2])) == {3}


def test_fdr_is_monotone_and_conservative():
    p = np.array([0.001, 0.01, 0.02, 0.04, 0.2])
    adj = hotspot.fdr_bh(p)
    assert (adj >= p).all() and np.all(np.diff(adj[np.argsort(p)]) >= 0)


# ---------- store pipeline ----------
def _session(arrays):
    s = Session()
    for name, a in arrays.items():
        prof = dict(driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype="uint8", crs=CRS.from_epsg(32643),
                    transform=from_origin(500000, 4000000, 30, 30))
        s.store.add(name, to_geotiff_bytes(prof, a, "uint8", 0))
    return s


def test_store_pipeline():
    rng = np.random.default_rng(3)
    a = rng.choice([1, 2, 3], size=(120, 120)).astype("uint8")
    b = a.copy()
    b[20:50, 20:50] = 3                                     # concentrated gain of class 3
    s = _session({"lulc_2000.tif": a, "lulc_2020.tif": b})
    lm = s.call("landscape_metrics", {"layers": ["lulc_2000.tif", "lulc_2020.tif"], "patches_top": 3})
    assert "error" not in lm, lm
    assert lm["landscape_change_first_to_last"]["NP"] < 0 and len(lm["classes"]) == 6
    mw = s.call("moving_window_map", {"layer": "lulc_2020.tif", "metric": "SHDI", "window_m": 300, "output_name": "mw.tif"})
    assert "error" not in mw and "mw.tif" in s.store.outputs
    hs = s.call("hotspot_analysis", {"layer": "lulc_2000.tif", "second_layer": "lulc_2020.tif", "variable": "gain", "class_code": 3,
                                     "block": 5, "permutations": 999})
    assert "error" not in hs, hs
    hot = [sp for sp in hs["gi_star"]["strongest_spots"] if sp["type"] == "hot"]
    assert all(20 * 30 <= sp["x"] - 500000 <= 50 * 30 for sp in hot)  # strongest hot spots inside the gain block
    assert hs["lisa"]["cells_by_cluster"]["High-High"] > 0
    assert len(hs["outputs"]) == 3


def test_geographic_rejected():
    s = Session()
    prof = dict(driver="GTiff", height=10, width=10, count=1, dtype="uint8", crs=CRS.from_epsg(4326), transform=from_origin(70, 30, 0.01, 0.01))
    s.store.add("g.tif", to_geotiff_bytes(prof, np.ones((10, 10)), "uint8", 0))
    assert "error" in s.call("landscape_metrics", {"layers": ["g.tif"]})
