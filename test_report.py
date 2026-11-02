"""Tests for v1.2.0: report generator (Word + HTML) built from a full analysis session."""
import io

import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin
from scipy import ndimage

import report
from session import Session
from store import to_geotiff_bytes
from test_simulate import _grow


@pytest.fixture(scope="module")
def full_session():
    H, W = 120, 140
    rng = np.random.default_rng(0)
    z = ndimage.gaussian_filter(rng.random((H, W)), 6)
    t0 = np.digitize(z, np.quantile(z, [.08, .55, .62])).astype("uint8") + 1
    road = np.zeros((H, W), bool)
    road[H // 2, :] = True
    t1 = _grow(t0, road, rng, 600, 500)
    t2 = _grow(t1, road, rng, 600, 500)
    s = Session()

    def prof(dt):
        return dict(driver="GTiff", height=H, width=W, count=1, dtype=dt, crs=CRS.from_epsg(32643), transform=from_origin(400000, 3500000, 30, 30))
    for n, a in [("lulc_2000.tif", t0), ("lulc_2010.tif", t1), ("lulc_2020.tif", t2)]:
        s.store.add(n, to_geotiff_bytes(prof("uint8"), a, "uint8", 0))
    s.store.add("dem.tif", to_geotiff_bytes(prof("float32"), np.add.outer(np.arange(H) * 2.0, np.zeros(W)).astype("float32"), "float32", -9999))
    labels = {"1": "Water", "2": "Forest", "3": "Built-up", "4": "Cropland"}
    calls = [
        ("intensity_analysis", {"layers": ["lulc_2000.tif", "lulc_2010.tif", "lulc_2020.tif"]}),
        ("landscape_metrics", {"layers": ["lulc_2000.tif", "lulc_2020.tif"]}),
        ("hotspot_analysis", {"layer": "lulc_2010.tif", "second_layer": "lulc_2020.tif", "variable": "gain", "class_code": 3, "block": 5, "permutations": 99}),
        ("driver_analysis", {"map_from": "lulc_2000.tif", "map_to": "lulc_2010.tif"}),
        ("simulate_lulc", {"map_from": "lulc_2000.tif", "map_to": "lulc_2010.tif", "year_from": 2000, "year_to": 2010, "year_target": 2020,
                           "output_name": "sim2020.tif", "validate_against": "lulc_2020.tif"}),
        ("curve_number_runoff", {"layers": ["lulc_2020.tif", "sim2020.tif"], "labels": labels}),
        ("rusle_erosion", {"layers": ["lulc_2020.tif"], "dem": "dem.tif", "labels": labels}),
        ("design_accuracy_sample", {"raster": "lulc_2020.tif"}),
        ("generate_sample_points", {"raster": "lulc_2020.tif", "n_per_class": {"1": 30, "2": 40, "3": 40, "4": 40}}),
    ]
    for name, args in calls:
        r = s.call(name, args)
        assert "error" not in r, (name, r)
    pts = s.tables["accuracy_points.csv"].copy()
    pts["reference_class"] = pts["map_class"]
    s.tables["ref.csv"] = pts
    assert "error" not in s.call("area_adjusted_accuracy", {"raster": "lulc_2020.tif", "table": "ref.csv", "reference_column": "reference_class",
                                                            "x_column": "x", "y_column": "y", "labels": labels})
    days = pd.date_range("2001-01-01", "2003-12-31")
    q = 5 + np.sin(np.arange(days.size) / 30) ** 2 * 10
    s.tables["q.csv"] = pd.DataFrame({"date": days, "obs": q, "sim": q * 1.05})
    assert "error" not in s.call("flow_evaluation", {"observed_table": "q.csv", "simulated_table": "q.csv", "date_column": "date",
                                                     "observed_column": "obs", "simulated_column": "sim", "split_date": "2003-01-01"})
    return s


def test_results_are_collected(full_session):
    tools = [x["tool"] for x in full_session.results]
    assert "simulate_lulc" in tools and "list_session" not in tools
    assert len(report.available(full_session)) >= 10


def test_report_docx_and_html(full_session):
    from docx import Document
    r = full_session.call("generate_report", {"title": "Test basin", "author": "Tester", "study_area": "Synthetic"})
    assert "error" not in r, r
    assert {"Accuracy assessment", "Land-cover change", "Landscape pattern and hotspots", "Drivers and scenario simulation",
            "Hydrological and erosion response"} <= set(r["sections"])
    assert r["tables"] >= 15 and r["figures"] >= 5
    files = full_session.report_files
    doc = Document(io.BytesIO(files["report.docx"]))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Test basin" in text and "Olofsson, P." in text and "Aldwaik" in text and "Moriasi" in text
    assert "Figure 1." in text and "Table 1." in text and len(doc.tables) == r["tables"] and len(doc.inline_shapes) == r["figures"]
    html = files["report.html"].decode()
    assert html.count("<figure>") == r["figures"] and "data:image/png;base64," in html and "Kappa simulation" in html


def test_selection_and_empty():
    s = Session()
    assert report.available(s) == []
    blocks, docx_b, html_b = report.generate(s, "Empty")
    assert docx_b[:2] == b"PK" and b"Empty" in html_b
