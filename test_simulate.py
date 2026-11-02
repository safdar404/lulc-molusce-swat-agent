"""Tests for v0.9.0: drivers, Markov-CA simulation and hindcast validation."""
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from scipy import ndimage

import simulate as S
from session import Session
from store import to_geotiff_bytes


def _grow(m, road, rng, n_urban, n_agri):
    a = m.copy()
    du = ndimage.distance_transform_edt(a != 3) * 30
    dr = ndimage.distance_transform_edt(~road) * 30
    p = np.exp(-du / 150) * 0.7 + np.exp(-dr / 300) * 0.3
    cand = np.flatnonzero((a != 3).ravel() & (a != 1).ravel())
    a.ravel()[cand[np.argsort(-(p.ravel()[cand] * rng.random(cand.size) ** 0.3))[:n_urban]]] = 3
    da = ndimage.distance_transform_edt(a != 4) * 30
    cand = np.flatnonzero((a == 2).ravel())
    a.ravel()[cand[np.argsort(-(np.exp(-da.ravel()[cand] / 200) * rng.random(cand.size) ** 0.3))[:n_agri]]] = 4
    return a


@pytest.fixture(scope="module")
def world():
    H, W = 160, 180
    rng = np.random.default_rng(0)
    z = ndimage.gaussian_filter(rng.random((H, W)), 7)
    t0 = np.digitize(z, np.quantile(z, [.08, .55, .62])).astype("uint8") + 1  # 1 water, 2 forest, 3 urban, 4 agriculture
    road = np.zeros((H, W), bool)
    road[H // 2, :] = True
    road[:, W // 3] = True
    t1 = _grow(t0, road, rng, 1000, 800)
    t2 = _grow(t1, road, rng, 1000, 800)
    prot = np.zeros((H, W), "uint8")
    prot[:50, 100:] = 1
    s = Session()

    def prof(dt):
        return dict(driver="GTiff", height=H, width=W, count=1, dtype=dt, crs=CRS.from_epsg(32643), transform=from_origin(400000, 3500000, 30, 30))
    for n, a in [("lulc_2000.tif", t0), ("lulc_2010.tif", t1), ("lulc_2020.tif", t2)]:
        s.store.add(n, to_geotiff_bytes(prof("uint8"), a, "uint8", 0))
    s.store.add("roads.tif", to_geotiff_bytes(prof("uint8"), road.astype("uint8"), "uint8", 255))
    s.store.add("dem.tif", to_geotiff_bytes(prof("float32"), (ndimage.gaussian_filter(rng.random((H, W)), 15) * 500).astype("float32"), "float32", -9999))
    s.store.add("protected.tif", to_geotiff_bytes(prof("uint8"), prot, "uint8", 255))
    return s, (t0, t1, t2), prot.astype(bool)


DRV = [{"type": "distance_to_class", "class": 3}, {"type": "distance_to_class", "class": 4}, {"type": "distance_to_layer", "name": "roads.tif"},
       {"type": "slope", "name": "dem.tif"}]


def test_primitives():
    m = np.zeros((5, 5), bool)
    m[2, 2] = True
    d = S.distance_to(m, 30.0)
    assert d[2, 2] == 0 and d[2, 4] == pytest.approx(60) and d[0, 0] == pytest.approx(30 * np.sqrt(8))
    dem = np.add.outer(np.zeros(6), np.arange(6) * 30.0)       # rises 30 m per 30 m cell -> 45 degrees
    assert S.slope_deg(dem, 30.0)[3, 3] == pytest.approx(45)
    x = np.r_[np.zeros(100), np.ones(100)]
    assert S.cramers_v(x, x.astype(int)) == pytest.approx(1.0) and S.cramers_v(np.random.default_rng(0).random(200), x.astype(int)) < 0.3
    P = np.array([[0.9, 0.1], [0.0, 1.0]])
    Q = S.markov_matrix(P * 100, np.array([1, 2]), 10, 20)
    np.testing.assert_allclose(Q, P @ P, atol=1e-9)                 # two calibration intervals = matrix squared
    np.testing.assert_allclose(S.markov_matrix(P * 100, np.array([1, 2]), 10, 5) @ S.markov_matrix(P * 100, np.array([1, 2]), 10, 5), P, atol=1e-6)
    i = np.array([1, 1, 1, 1, 2, 2])
    assert S.kappa_simulation(i, np.array([1, 2, 1, 1, 2, 2]), np.array([1, 2, 1, 1, 2, 2])) == pytest.approx(1.0)


def test_driver_screening_finds_true_drivers(world):
    s, _, _ = world
    r = s.call("driver_analysis", {"map_from": "lulc_2000.tif", "map_to": "lulc_2010.tif", "drivers": DRV})
    assert "error" not in r, r
    auc = {(x["transition"], x["driver"]): x["auc"] for x in r["screening"]}
    assert auc[("2->3", "dist_class_3")] > 0.85 and auc[("2->3", "slope_dem")] < 0.65   # true driver vs irrelevant one
    assert set(r["vif"]) == {"dist_class_3", "dist_class_4", "dist_roads", "slope_dem"}


@pytest.mark.parametrize("model", S.POTENTIAL_MODELS)
def test_hindcast_beats_null_and_random(world, model):
    s, (t0, t1, t2), _ = world
    r = s.call("simulate_lulc", {"map_from": "lulc_2000.tif", "map_to": "lulc_2010.tif", "year_from": 2000, "year_to": 2010, "year_target": 2020,
                                 "drivers": DRV, "model": model, "output_name": f"h_{model[:3]}.tif", "validate_against": "lulc_2020.tif"})
    assert "error" not in r, r
    v = {x["model"]: x for x in r["validation"]["results"]}
    sim = v[f"h_{model[:3]}.tif"]
    assert sim["fom"] > 0.2 and sim["kappa_simulation"] > 0.3
    assert v["Null (persistence)"]["fom"] == 0
    assert sim["quantity_disagreement"] < v["Null (persistence)"]["quantity_disagreement"]
    assert f"h_{model[:3]}.tif" in s.store.names()


def test_scenarios_and_protection(world):
    s, (_, _, t2), prot = world
    base = dict(map_from="lulc_2010.tif", map_to="lulc_2020.tif", year_from=2010, year_to=2020, year_target=2030, drivers=DRV[:3],
                growth_classes=[3], natural_classes=[2], protected_layer="protected.tif")
    urban = {}
    for sc in S.SCENARIOS:
        r = s.call("simulate_lulc", dict(base, scenario=sc, output_name=f"{sc[:3]}.tif"))
        assert "error" not in r, r
        urban[sc] = next(a["simulated_ha"] for a in r["simulation"]["area_table"] if a["class"] == 3)
    assert urban["Ecological protection"] < urban["Business as usual"] < urban["Development priority"]
    eco = s.store.get("Eco.tif").data
    assert int(((eco != t2) & prot).sum()) == 0
    r = s.call("simulate_lulc", dict(base, forbidden=["2->3"], output_name="forb.tif"))
    assert r["simulation"]["demand_pixels"].get("2->3", 0) == 0
    f = s.store.get("forb.tif").data
    assert int(((t2 == 2) & (f == 3)).sum()) == 0


def test_driver_layers_and_errors(world):
    s, _, _ = world
    r = s.call("make_driver_layers", {"base_map": "lulc_2020.tif", "classes": [3], "layers": ["roads.tif"], "dem": "dem.tif"})
    assert len(r["outputs"]) == 3 and all(n in s.store.names() for n in r["outputs"])
    assert "error" in s.call("simulate_lulc", {"map_from": "lulc_2010.tif", "map_to": "lulc_2000.tif", "year_from": 2010, "year_to": 2000, "year_target": 2030})
