"""Offline tests for v1.3.0 imagery download: a fake STAC client serves local cloud-optimised GeoTIFFs."""
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

import imagery as I
from session import Session

LON, LAT = 73.05, 33.70                       # Islamabad, UTM 43N
UTM = CRS.from_epsg(32643)


def _cog(path, arr, transform, nodata=0, dtype="uint16"):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=dtype, crs=UTM, transform=transform,
                       nodata=nodata, tiled=True, blockxsize=256, blockysize=256) as d:
        d.write(arr.astype(dtype), 1)
    return str(path)


class FakeClient:
    def __init__(self, items):
        self.items = items
        self.signed = 0

    def search(self, collection, bbox, start, end, max_cloud=None, limit=200, query=None):
        out = [it for it in self.items.get(collection, []) if start <= it["properties"].get("datetime", start)[:10] <= end]
        if max_cloud is not None:
            out = [it for it in out if it["properties"].get("eo:cloud_cover", 0) < max_cloud]
        return out

    def sign(self, collection, href):
        self.signed += 1
        return href


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("cogs")
    crs, tr, shape = I.target_grid(I.bbox_from_center(LON, LAT, 3), 10)
    H, W = shape
    # source scenes on a slightly larger 10 m grid
    src_tr = from_origin(tr.c - 200, tr.f + 200, 10, 10)
    Hs, Ws = H + 40, W + 40
    truth = np.array([0.05, 0.08, 0.06, 0.12, 0.25, 0.30, 0.32, 0.33, 0.20, 0.12])
    items = []
    for k, (date, pb, cloud_rows) in enumerate([("2021-03-01", "02.14", slice(0, Hs // 2)), ("2023-03-11", "05.09", slice(Hs // 2, Hs)),
                                                ("2023-04-01", "05.09", slice(0, 0))]):
        scl = np.full((Hs, Ws), 4, "uint8")
        scl[cloud_rows] = 9                     # cloud high probability
        assets = {"SCL": {"href": _cog(d / f"s{k}_SCL.tif", scl, src_tr, 0, "uint8")}}
        off = 1000 if float(pb) >= 4 else 0
        for b, t in zip(I.PRODUCTS["Sentinel-2 L2A"]["bands"], truth):
            dn = np.full((Hs, Ws), t * 10000 + off, "float32")
            dn[cloud_rows] = 9000                # bright cloud must be masked
            if k == 2:
                dn += 300                        # a third, slightly different clear scene
            assets[b] = {"href": _cog(d / f"s{k}_{b}.tif", dn, src_tr)}
        items.append(dict(id=f"S2_{date}", properties={"datetime": f"{date}T05:00:00Z", "eo:cloud_cover": 10.0 + k, "s2:processing_baseline": pb,
                                                       "platform": "sentinel-2a", "s2:mgrs_tile": "43SCT"}, assets=assets))
    dem = np.add.outer(np.arange(Hs) * 1.0, np.arange(Ws) * 0.5).astype("float32") + 500
    wc = np.where(np.arange(Ws)[None, :] < Ws // 2, 10, 50).repeat(Hs, 0).astype("uint8")
    dem_item = dict(id="dem", properties={"datetime": "2021-04-22T00:00:00Z"}, assets={"data": {"href": _cog(d / "dem.tif", dem, src_tr, None, "float32")}})
    wc_item = dict(id="wc", properties={"datetime": "2021-06-01T00:00:00Z"}, assets={"map": {"href": _cog(d / "wc.tif", wc, src_tr, 0, "uint8")}})
    client = FakeClient({"sentinel-2-l2a": items, "cop-dem-glo-30": [dem_item], "esa-worldcover": [wc_item]})
    return client, truth


def test_grid_and_masks():
    bb = I.bbox_from_center(LON, LAT, 10)
    assert bb[2] - bb[0] == pytest.approx(10 / (111.32 * np.cos(np.radians(LAT))), rel=1e-6)
    crs, tr, shape = I.target_grid(bb, 30)
    assert crs.to_epsg() == 32643 and shape[0] == pytest.approx(10000 / 30, abs=15) and tr.a == 30
    assert I.utm_epsg(-70, -33) == 32719
    assert list(I.s2_clear(np.array([0, 3, 4, 5, 6, 8, 9, 10, 11]))) == [False, False, True, True, True, False, False, False, True]
    qa = np.array([21824, 21952, 22280, 23888, 1, 30048, 22018, 55052, 54596, 29448])
    # clear land, clear water, high-conf cloud, shadow, fill, snow, dilated-cloud buffer, cloud+cirrus, high-conf cirrus,
    # glacier ice that Fmask calls high-confidence cloud but also high-confidence snow/ice (kept by the snow-aware mask)
    assert list(I.landsat_clear(qa)) == [True, True, False, False, False, True, True, False, False, True]
    assert list(I.landsat_clear(qa, strict=True)) == [True, True, False, False, False, True, False, False, False, False]
    assert I.s2_offset({"properties": {"s2:processing_baseline": "05.09"}}) == -1000 and I.s2_offset({"properties": {"s2:processing_baseline": "02.14"}}) == 0
    assert I.to_reflectance("Landsat 4-9 C2 L2", np.array([10000.0]), {})[0] == pytest.approx(0.075)


def test_composite_masks_clouds_and_offsets(world):
    client, truth = world
    s = Session()
    r = I.download_composite(s.store, client, "Sentinel-2 L2A", I.bbox_from_center(LON, LAT, 3), "2021-01-01", "2023-03-31", 50, 6)
    assert len(r["scenes_used"]) == 2 and r["pixels_with_data_pct"] == pytest.approx(100)
    s.store.add(r["output"], s.store.outputs[r["output"]])
    st = s.store.get(r["output"])
    assert st.bands.shape[0] == 10
    # cloudy halves replaced by the other scene; offset of the newer baseline removed -> exact reflectance everywhere
    for b in range(10):
        np.testing.assert_allclose(st.bands[b][~st.mask] / 10000, truth[b], atol=2e-4)
    cnt = s.store.add("c", s.store.outputs[r["observation_count"]], register=False)
    assert set(np.unique(cnt.data)) == {1}


def test_composite_feeds_classifier_preset(world):
    import classify
    client, _ = world
    s = Session()
    r = I.download_composite(s.store, client, "Sentinel-2 L2A", I.bbox_from_center(LON, LAT, 3), "2023-01-01", "2023-12-31", 50, 2, output_name="comp.tif")
    s.store.add("comp.tif", s.store.outputs["comp.tif"])
    bm, sc, of = classify.preset_band_map(s.store, "comp.tif", r["preset"])
    res = classify.compute_index_rasters(s.store, bm, ["NDVI"], sc, of)
    # upper half: median of the true scene and the +0.03 scene (= +0.015); lower half: only the +0.03 scene (the other is cloudy there)
    up, lo = (0.335 - 0.075) / (0.335 + 0.075), (0.35 - 0.09) / (0.35 + 0.09)
    assert res["indices"][0]["mean"] == pytest.approx((up + lo) / 2, abs=0.005)


def test_template_grid_dem_and_worldcover(world):
    client, _ = world
    s = Session()
    I.download_composite(s.store, client, "Sentinel-2 L2A", I.bbox_from_center(LON, LAT, 3), "2023-01-01", "2023-12-31", 50, 2, res=20, output_name="c20.tif")
    s.store.add("c20.tif", s.store.outputs["c20.tif"])
    d = I.download_dem(s.store, client, template="c20.tif")
    w = I.download_worldcover(s.store, client, template="c20.tif", year=2021)
    s.store.add(d["output"], s.store.outputs[d["output"]])
    s.store.add(w["output"], s.store.outputs[w["output"]])
    g, dem, wc = s.store.get("c20.tif"), s.store.get(d["output"]), s.store.get(w["output"])
    assert dem.data.shape == wc.data.shape == g.data.shape and dem.transform == g.transform
    assert d["coverage_pct"] == pytest.approx(100) and 500 < d["min_m"] < d["max_m"]
    assert set(w["class_area_ha"]) == {"10 Tree cover", "50 Built-up"}


def test_limits_and_errors(world):
    client, _ = world
    s = Session()
    with pytest.raises(ValueError, match="limit"):
        I.download_composite(s.store, client, "Sentinel-2 L2A", I.bbox_from_center(LON, LAT, 40), "2023-01-01", "2023-12-31", 50, 2)
    with pytest.raises(ValueError, match="No scenes"):
        I.download_composite(s.store, client, "Sentinel-2 L2A", I.bbox_from_center(LON, LAT, 3), "2010-01-01", "2010-12-31", 50, 2)


def test_client_pagination_and_signing():
    class Resp:
        def __init__(self, js):
            self.js = js

        def raise_for_status(self):
            pass

        def json(self):
            return self.js

    class Http:
        def __init__(self):
            self.posts, self.gets = [], 0

        def post(self, url, json, timeout):
            self.posts.append((url, json))
            if len(self.posts) == 1:
                return Resp({"features": [{"id": "a"}], "links": [{"rel": "next", "href": "https://x/next", "body": {"token": "p2"}}]})
            return Resp({"features": [{"id": "b"}], "links": []})

        def get(self, url, timeout):
            self.gets += 1
            return Resp({"token": "sv=1&sig=abc", "msft:expiry": "2099-01-01T00:00:00Z"})

    h = Http()
    c = I.Client(session=h)
    items = c.search("sentinel-2-l2a", (1, 2, 3, 4), "2023-01-01", "2023-02-01", 20)
    assert [i["id"] for i in items] == ["a", "b"] and h.posts[0][1]["query"]["eo:cloud_cover"]["lt"] == 20 and h.posts[1][1] == {"token": "p2"}
    assert c.sign("sentinel-2-l2a", "https://b/x.tif") == "https://b/x.tif?sv=1&sig=abc"
    c.sign("sentinel-2-l2a", "https://b/y.tif")
    assert h.gets == 1                                   # token cached


def test_agent_tools_and_report(world):
    import report
    client, _ = world
    s = Session()
    s.img_client = client
    f = s.call("search_scenes", {"product": "Sentinel-2 L2A", "start": "2021-01-01", "end": "2023-12-31", "center_lon": LON, "center_lat": LAT, "size_km": 3})
    assert f["found"] == 3 and f["scenes"][0]["cloud"] <= f["scenes"][1]["cloud"]
    c = s.call("download_composite", {"product": "Sentinel-2 L2A", "start": "2023-01-01", "end": "2023-12-31", "center_lon": LON, "center_lat": LAT,
                                      "size_km": 3, "n_scenes": 2, "output_name": "s2.tif"})
    assert "error" not in c, c
    assert s.call("inspect_raster", {"layer": "s2.tif"})["bands"] == 10
    w = s.call("download_worldcover", {"template": "s2.tif"})
    d = s.call("download_dem", {"template": "s2.tif"})
    assert "error" not in w and "error" not in d
    blocks = report.build(s, {"title": "t"})
    assert any(b[0] == "h1" and b[1] == "Data acquisition" for b in blocks)
    assert "error" in s.call("download_composite", {"product": "Sentinel-2 L2A", "start": "2023-01-01", "end": "2023-12-31"})   # no area


def test_scene_selection_covers_every_tile():
    items = [{"id": f"{t}_{k}"} for t in ("150/035", "149/035", "150/036") for k in range(5)]
    rows = [{"tile": i["id"].split("_")[0], "cloud": k} for k, i in enumerate(items)]
    order = np.argsort([r["cloud"] % 5 for r in rows], kind="stable")      # sorted by cloud, tiles interleaved
    items, rows = [items[i] for i in order], [rows[i] for i in order]
    sel, tiles = I.select_scenes(items, rows, 2)
    assert len(tiles) == 3 and len(sel) == 6
    assert sorted({s["id"].split("_")[0] for s in sel}) == tiles


def test_gap_fill_for_persistently_flagged_glacier(tmp_path):
    """v1.4.3: pixels flagged in EVERY scene (glacier ice that Fmask calls cloud / cirrus) are filled from all valid observations,
    reported separately, and the rejection reasons are counted."""
    crs, tr, shape = I.target_grid(I.bbox_from_center(LON, LAT, 2), 30)
    H, W = shape
    src_tr = from_origin(tr.c - 300, tr.f + 300, 30, 30)
    Hs, Ws = H + 20, W + 20
    items = []
    for k in range(3):
        qa = np.full((Hs, Ws), 21824, "uint16")                 # clear land
        qa[:, : Ws // 2] = 8 + (3 << 8) + (3 << 14)             # left half: high-confidence cloud + cirrus in every scene ("glacier")
        assets = {"qa_pixel": {"href": _cog(tmp_path / f"l{k}_qa.tif", qa, src_tr)}}
        for b in I.PRODUCTS["Landsat 4-9 C2 L2"]["bands"]:
            assets[b] = {"href": _cog(tmp_path / f"l{k}_{b}.tif", np.full((Hs, Ws), 20000 + 1000 * k, "float32"), src_tr)}
        items.append(dict(id=f"LC09_{k}", properties={"datetime": f"2025-08-0{k + 1}T05:00:00Z", "eo:cloud_cover": 5.0 + k,
                                                      "landsat:wrs_path": "150", "landsat:wrs_row": "035", "platform": "landsat-9"}, assets=assets))
    client = FakeClient({"landsat-c2-l2": items})
    bb = I.bbox_from_center(LON, LAT, 2)
    s = Session()
    r = I.download_composite(s.store, client, "Landsat 4-9 C2 L2", bb, "2025-08-01", "2025-09-30", 50, 4, output_name="g.tif")
    assert r["pixels_with_data_pct"] == pytest.approx(100, abs=0.5)
    assert 40 < r["gap_filled_pct"] < 60 and r["clear_pct"] + r["gap_filled_pct"] == pytest.approx(r["pixels_with_data_pct"])
    assert list(r["mask_rejections_pct"])[0] == "cloud (high conf.)" and "gap-filled" in r["note"]
    g = s.store.add("g", s.store.outputs["g.tif"], register=False)
    np.testing.assert_allclose(g.bands[0][~g.mask] / 1e4, 21000 * 2.75e-5 - 0.2, atol=2e-4)   # median of the three scenes everywhere
    r2 = I.download_composite(s.store, client, "Landsat 4-9 C2 L2", bb, "2025-08-01", "2025-09-30", 50, 4, output_name="n.tif", fill_gaps=False)
    assert r2["gap_filled_pct"] == 0 and r2["pixels_with_data_pct"] == pytest.approx(r["clear_pct"])
