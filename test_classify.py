"""Tests for v0.8.0: multi-band store, spectral indices and the classification engine."""
import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_origin, xy
from scipy import ndimage

import classify
from session import Session

S2 = list(classify.PRESETS)[0]
SIG = {1: [.06, .05, .03, .03, .02, .02, .02, .02, .01, .01], 2: [.04, .07, .04, .10, .25, .30, .33, .34, .18, .09],
       3: [.10, .11, .12, .13, .14, .15, .16, .16, .22, .20], 4: [.12, .15, .19, .21, .23, .24, .25, .26, .32, .27]}


def _scene(noise=0.03, seed=0, H=160, W=180):
    rng = np.random.default_rng(seed)
    z = ndimage.gaussian_filter(rng.random((H, W)), 6)
    truth = np.digitize(z, np.quantile(z, [.25, .5, .75])).astype("uint8") + 1
    st = np.zeros((10, H, W), "float32")
    for c, v in SIG.items():
        st[:, truth == c] = np.array(v)[:, None]
    st += rng.normal(0, noise, st.shape)
    dn = np.clip(st * 10000, 1, 10000).astype("uint16")
    prof = dict(driver="GTiff", height=H, width=W, count=10, dtype="uint16", crs=CRS.from_epsg(32643),
                transform=from_origin(500000, 4000000, 10, 10), nodata=0)
    with MemoryFile() as mf:
        with mf.open(**prof) as d:
            d.write(dn)
        raw = mf.read()
    s = Session()
    s.store.add("s2.tif", raw)
    rr, cc = rng.integers(0, H, 600), rng.integers(0, W, 600)
    xs, ys = xy(prof["transform"], rr, cc)
    s.tables["train.csv"] = pd.DataFrame(dict(x=xs, y=ys, cls=truth[rr, cc]))
    return s, truth


def test_multiband_store_and_band_access():
    s, _ = _scene()
    assert s.store.band_count("s2.tif") == 10
    assert "s2.tif#7" in s.store.names()
    b7 = s.store.get("s2.tif#7")
    assert b7.data.shape == (160, 180) and not np.shares_memory(b7.data, s.store.get("s2.tif#3").data)
    assert s.call("inspect_raster", {"layer": "s2.tif"})["bands"] == 10
    assert "error" in s.call("inspect_raster", {"layer": "s2.tif#11"})


def test_index_formulas():
    b = dict(nir=np.array([0.4]), red=np.array([0.1]), blue=np.array([0.05]), green=np.array([0.08]), swir1=np.array([0.2]))
    assert classify.INDICES["NDVI"][1](b)[0] == pytest.approx(0.6, rel=1e-4)
    assert classify.INDICES["EVI"][1](b)[0] == pytest.approx(2.5 * 0.3 / (0.4 + 0.6 - 0.375 + 1))
    assert classify.INDICES["SAVI"][1](b)[0] == pytest.approx(1.5 * 0.3 / 1.0)
    assert classify.INDICES["MNDWI"][1](b)[0] == pytest.approx((0.08 - 0.2) / 0.28, rel=1e-4)
    assert classify.available_indices({"nir": 1, "red": 1}) == ["NDVI", "SAVI", "MSAVI"]


def test_spectral_index_tool_registers_layers():
    s, truth = _scene(noise=0)
    r = s.call("spectral_indices", {"stack": "s2.tif", "preset": S2, "indices": ["NDVI", "NDWI"], "prefix": "t_"})
    assert "error" not in r, r
    ndvi = s.store.get("t_NDVI.tif").data
    assert ndvi[truth == 2].mean() > 0.7 and ndvi[truth == 1].mean() < 0   # vegetation vs water
    assert "t_NDVI.tif" in s.store.names()


@pytest.mark.parametrize("model", classify.MODELS)
def test_classifiers_recover_truth(model):
    s, truth = _scene()
    r = s.call("classify_image", {"table": "train.csv", "class_column": "cls", "x_column": "x", "y_column": "y", "stack": "s2.tif",
                                  "preset": S2, "indices": ["NDVI", "MNDWI", "NDBI"], "texture": True, "model": model, "n_trees": 60,
                                  "block_m": 400, "smooth": 3, "output_name": "map.tif"})
    assert "error" not in r, r
    assert r["cross_validation"]["spatial_block_kfold"]["overall_accuracy"] > 0.9
    m = s.store.get("map.tif").data
    assert (m == truth).mean() > 0.95
    assert len(r["feature_importance"]) == len(r["features"])


def test_spatial_cv_is_not_more_optimistic_with_clustered_noisy_samples():
    s, truth = _scene(noise=0.12, seed=3)
    rng = np.random.default_rng(1)
    rows, cols = [], []
    for _ in range(15):  # clustered sampling
        r0, c0 = rng.integers(8, 150), rng.integers(8, 170)
        rows += list(r0 + rng.integers(-6, 7, 40))
        cols += list(c0 + rng.integers(-6, 7, 40))
    rows, cols = np.clip(rows, 0, 159), np.clip(cols, 0, 179)
    g = s.store.get("s2.tif")
    xs, ys = xy(g.transform, rows, cols)
    s.tables["clustered.csv"] = pd.DataFrame(dict(x=xs, y=ys, cls=truth[rows, cols]))
    r = s.call("classify_image", {"table": "clustered.csv", "class_column": "cls", "x_column": "x", "y_column": "y", "stack": "s2.tif",
                                  "preset": S2, "texture": True, "n_trees": 80, "block_m": 300, "predict": False})
    cv = r["cross_validation"]
    assert cv["optimism_gap_oa"] >= -0.01


def test_kmeans_and_errors():
    s, truth = _scene(noise=0.01)
    r = s.call("cluster_image", {"stack": "s2.tif", "preset": S2, "k": 4, "output_name": "km.tif"})
    assert "error" not in r, r
    km = s.store.get("km.tif").data
    # each true class maps (almost) to a single cluster
    purity = sum(np.bincount(km[truth == c]).max() for c in range(1, 5)) / truth.size
    assert purity > 0.95
    s.tables["one.csv"] = s.tables["train.csv"].assign(cls=1)
    assert "error" in s.call("classify_image", {"table": "one.csv", "class_column": "cls", "x_column": "x", "y_column": "y",
                                                "stack": "s2.tif", "preset": S2})
    assert "error" in s.call("classify_image", {"table": "train.csv", "class_column": "cls", "x_column": "x", "y_column": "y",
                                                "stack": "s2.tif", "preset": list(classify.PRESETS)[2], "indices": ["NDRE"]})
