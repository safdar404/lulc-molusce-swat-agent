"""Tests for the flat-layout analysis core. Run with `pytest -q` from the repository root."""

import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

import agent_tools
import hydro
import knowledge
import metrics
from session import Session
from store import to_geotiff_bytes


# ---------- statistics ----------
def test_confusion_matrix_and_accuracy_hand_computed():
    m, cls = metrics.confusion_matrix([1, 1, 2, 2, 2, 3], [1, 2, 2, 2, 3, 3])
    assert cls == [1, 2, 3]
    assert m.tolist() == [[1, 1, 0], [0, 2, 1], [0, 0, 1]]
    r = metrics.accuracy_from_matrix(m)
    assert r["overall_accuracy"] == pytest.approx(4 / 6)
    pe = (2 * 1 + 3 * 3 + 1 * 2) / 36
    assert r["kappa"] == pytest.approx((4 / 6 - pe) / (1 - pe))
    assert r["producers_accuracy"] == pytest.approx([1 / 2, 2 / 3, 1.0])
    assert r["users_accuracy"] == pytest.approx([1.0, 2 / 3, 1 / 2])


def test_pontius_and_figure_of_merit():
    d = metrics.pontius_disagreement([[40, 10], [0, 50]])
    assert d["total"] == pytest.approx(0.10)
    assert d["quantity"] == pytest.approx(0.10)
    assert d["allocation"] == pytest.approx(0.0)
    f = metrics.figure_of_merit([1, 1, 1, 1], [2, 2, 1, 3], [2, 1, 2, 2])
    assert (f["hits"], f["misses"], f["false_alarms"], f["wrong_hits"]) == (1, 1, 1, 1)
    assert f["fom"] == pytest.approx(0.25)


def test_hydro_metrics():
    o = np.array([1.0, 2.0, 3.0, 4.0])
    assert metrics.nse(o, o) == pytest.approx(1.0)
    assert metrics.kge(o, o) == pytest.approx(1.0)
    assert metrics.pbias(o, o * 0.9) == pytest.approx(10.0)  # positive = underestimation
    assert metrics.r2(o, 2 * o + 1) == pytest.approx(1.0)
    obs = pd.DataFrame({"date": ["2020-01-01", "2020-01-02", "2020-01-03"], "q": [1, 2, 3]})
    sim = pd.DataFrame({"date": ["2020-01-02", "2020-01-03", "2020-01-04"], "q": [2, 3, 9]})
    r = hydro.compute(obs, sim, "date", "q", "q")
    assert r["n_pairs"] == 2 and r["nse"] == pytest.approx(1.0)


# ---------- rasters through the tool registry ----------
def _tif(arr, nodata=0):
    profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=str(arr.dtype),
                   crs=CRS.from_epsg(32643), transform=from_origin(500000, 4000000, 30, 30), nodata=nodata)
    return to_geotiff_bytes(profile, arr, str(arr.dtype), nodata)


@pytest.fixture
def ctx():
    s = Session()
    s.store.add("lulc2000.tif", _tif(np.array([[1, 1, 2], [2, 3, 0]], dtype="uint8")))
    s.store.add("lulc2020.tif", _tif(np.array([[1, 2, 2], [2, 3, 0]], dtype="uint8")))
    return s


def test_area_stats(ctx):
    r = ctx.call("lulc_area_stats", {"layer": "lulc2000.tif", "labels": {"1": "Water"}})
    assert "error" not in r, r
    assert r["pixel_area_m2"] == 900
    assert r["total_ha"] == pytest.approx(5 * 0.09)
    assert [c["pixels"] for c in r["classes"]] == [2, 2, 1]
    assert r["classes"][0]["name"] == "Water"


def test_geometry_and_transitions(ctx):
    g = ctx.call("check_geometry_match", {"layers": ["lulc2000.tif", "lulc2020.tif"]})
    assert g["all_match"] is True
    t = ctx.call("transition_matrix", {"old_layer": "lulc2000.tif", "new_layer": "lulc2020.tif"})
    assert t["top_conversions"][0] == dict(area_ha=0.09, from_code=1, to_code=2)
    assert t["persistence_percent"] == pytest.approx(80.0)
    h = ctx.call("hindcast_validation", {"observed": "lulc2020.tif", "simulated": "lulc2000.tif", "initial": "lulc2000.tif"})
    assert h["compared_pixels"] == 5 and h["figure_of_merit"]["misses"] == 1
    out = ctx.call("transition_raster", {"old_layer": "lulc2000.tif", "new_layer": "lulc2020.tif", "output_name": "tr.tif"})
    assert "error" not in out and "tr.tif" in ctx.store.outputs


def test_registry_and_log(ctx):
    names = {s["name"] for s in agent_tools.schemas()}
    assert {"list_session", "inspect_raster", "hydro_metrics", "practical_guide"} <= names
    assert agent_tools.run_tool(ctx, "nope", {})["error"].startswith("Unknown tool")
    assert "error" in ctx.call("inspect_raster", {"layer": "missing.tif"})
    ctx.call("list_session")
    assert list(ctx.log_df()["input"]) == ["list_session"]


def test_knowledge_guide():
    assert knowledge.guide("8")["title"] == "Accuracy assessment"
    assert any(m["practical"] == 19 for m in knowledge.guide("hindcast")["matches"])
    assert len(knowledge.PRACTICALS) == 30


def test_describe_table_and_offline_analysis(ctx):
    import agent
    ctx.tables["pts.csv"] = pd.DataFrame({"x": [1.0, 2.0, None], "y": [3.0, 4.0, 5.0], "cls": ["a", "b", "a"]})
    d = ctx.call("describe_table", {"table": "pts.csv"})
    assert d["rows"] == 3 and d["missing"] == {"x": 1} and d["categorical_summary"]["cls"]["unique"] == 2
    text = agent.offline_analysis(ctx)
    assert "pts.csv" in text and "lulc2000.tif" in text and "share one grid" in text and "Accuracy" in text


def test_friendly_error_messages():
    import agent

    class BadRequestError(Exception):
        pass
    assert "no credit" in agent.friendly_error(BadRequestError("Your credit balance is too low to access the Anthropic API"))
    assert "rejected" in agent.friendly_error(type("AuthenticationError", (Exception,), {})("invalid x-api-key"))


def test_run_agent_rolls_back_history_on_failure(monkeypatch):
    import sys
    import types

    import agent

    class Boom(Exception):
        pass

    class Client:
        def __init__(self, api_key):
            self.messages = self

        def create(self, **kw):
            raise Boom("credit balance is too low")
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    msgs = []
    with pytest.raises(Boom):
        agent.run_agent("k", "m", msgs, Session(), "hi")
    assert msgs == []


# ---------- live canvas + cartography ----------
def test_live_jobs_and_map_layout():
    import cartography, live
    s = Session()
    prof = dict(driver="GTiff", height=60, width=80, count=1, crs=CRS.from_epsg(32643), transform=from_origin(300000, 3700000, 30, 30))
    a = np.ones((60, 80), "uint8"); a[:, 40:] = 2
    b = a.copy(); b[:30, :40] = 2
    s.store.add("t1.tif", to_geotiff_bytes(prof, a, "uint8", 0))
    s.store.add("t2.tif", to_geotiff_bytes(prof, b, "uint8", 0))
    job = live.build(s.store, "LULC change (from → to)", ["t1.tif", "t2.tif"], labels={"1": "Forest", "2": "Built-up"})
    frames = list(live.run(job, 6))
    assert len(frames) == 6 and job.rows_done == 60
    st = job.stats()
    assert st["changed %"] == pytest.approx(25.0)
    assert st["classes"][12] == pytest.approx(30 * 40 * 900 / 1e4)
    assert job.labels["12"] == "Forest → Built-up"
    png = cartography.fig_bytes(cartography.compose_map(job.arr, job.mask, job.transform, job.crs, kind=job.kind, title="t", labels=job.labels), "png", 60)
    assert png[:4] == b"\x89PNG"
    f = cartography.preview_frame(job.arr, job.mask, 30, kind=job.kind, **live.frame_style(job, [s.store.get("t1.tif"), s.store.get("t2.tif")]))
    assert f.shape == (60, 80, 3)
    s.store.outputs["x.tif"] = job.geotiff()
    assert s.store.get("x.tif").data.max() == 22  # outputs are readable as inputs


def test_scalebar_nice_numbers():
    import cartography
    assert cartography._nice(3700) == 2500 and cartography._nice(0.9) == 0.5


def test_layers_toc_items():
    """v1.4.8: the sidebar table of contents lists every loaded raster, output, vector, table and an active job."""
    import types
    import geopandas as gpd
    from shapely.geometry import Point
    import ui
    s = Session()
    prof = dict(driver="GTiff", width=4, height=3, count=1, dtype="uint8", crs=CRS.from_epsg(32643),
                transform=from_origin(500000, 4000000, 30, 30), nodata=0)
    s.store.add("lulc_2020.tif", to_geotiff_bytes(prof, np.array([[0, 1, 2, 3]] * 3), "uint8", 0))
    s.store.outputs["change.tif"] = b"x" * 2000
    s.tables["points.csv"] = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    s.vectors["basin"] = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=4326)
    job = types.SimpleNamespace(name="composite", running=True, progress=0.4, message="Scene 3/11", error=None)
    g = {title: rows for _, title, rows in ui.toc_items(s, job)}
    r = g["Raster layers"][0]
    assert r["name"] == "lulc_2020.tif" and r["tag"] == "upload"
    assert "4×3 px" in r["detail"] and "30 m" in r["detail"] and "EPSG:32643" in r["detail"] and "75% valid" in r["detail"]
    assert g["Generated outputs (not loaded as layers)"][0]["name"] == "change.tif"
    assert "1 feature ·" in g["Vector layers"][0]["detail"] and "EPSG:4326" in g["Vector layers"][0]["detail"]
    assert g["Tables"][0]["detail"] == "2 rows × 2 cols"
    assert g["Background jobs"][0]["tag"] == "running" and "40%" in g["Background jobs"][0]["detail"]
    assert all(not rows for _, _, rows in ui.toc_items(Session()))
