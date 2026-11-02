"""Streamlit tab (v1.3.0): download cloud-free composites, DEM and WorldCover for an area of interest."""
import datetime

import pandas as pd
import streamlit as st

import imagery as I
import ui


def _client():
    if "img_client" not in st.session_state:
        st.session_state.img_client = I.Client()
    return st.session_state.img_client


def _aoi(ctx, R, key):
    """Area of interest as a lon/lat bbox, or a template raster whose grid is reused."""
    mode = st.radio("Area of interest", ["Centre point + size", "Bounding box (lon/lat)", "Extent and grid of a loaded raster", "Extent of a loaded vector"],
                    horizontal=True, key=f"{key}_mode")
    template, bbox = None, None
    st.session_state[f"{key}_clipgdf"] = None
    if mode == "Centre point + size":
        c = st.columns(3)
        lat = c[0].number_input("Latitude", -85.0, 85.0, 33.6844, format="%.5f", key=f"{key}_lat")
        lon = c[1].number_input("Longitude", -180.0, 180.0, 73.0479, format="%.5f", key=f"{key}_lon")
        km = c[2].number_input("Width = height (km)", 1.0, 200.0, 10.0, 1.0, key=f"{key}_km")
        bbox = I.bbox_from_center(lon, lat, km)
    elif mode == "Bounding box (lon/lat)":
        c = st.columns(4)
        w = c[0].number_input("West", -180.0, 180.0, 72.95, format="%.5f", key=f"{key}_w")
        s = c[1].number_input("South", -85.0, 85.0, 33.60, format="%.5f", key=f"{key}_s")
        e = c[2].number_input("East", -180.0, 180.0, 73.15, format="%.5f", key=f"{key}_e")
        n = c[3].number_input("North", -85.0, 85.0, 33.78, format="%.5f", key=f"{key}_n")
        bbox = (w, s, e, n)
    elif mode == "Extent and grid of a loaded raster":
        maps = [r for r in R if "#" not in r]
        if not maps:
            st.info("Upload or create a raster first.")
            return None, None
        template = st.selectbox("Raster (its CRS, pixel size and extent are reused, so outputs align exactly)", maps, key=f"{key}_tpl")
        vs = ctx.__dict__.get("vectors", {})
        if vs:
            cv = st.selectbox("Clip to polygon (optional)", ["(none)"] + list(vs), key=f"{key}_tplclip")
            st.session_state[f"{key}_clipgdf"] = None if cv == "(none)" else cv
    else:
        vs = ctx.__dict__.get("vectors", {})
        if not vs:
            st.info("Upload a vector (study-area boundary) in the sidebar first.")
            return None, None
        c = st.columns([2, 1])
        v = c[0].selectbox("Vector layer (e.g. basin boundary from a KMZ, shapefile or GeoPackage)", list(vs), key=f"{key}_vec")
        bbox = I.vector_bbox(vs[v])
        if c[1].checkbox("Clip to the polygon", True, key=f"{key}_clip", help="Pixels outside the basin become no data, so all statistics cover the basin only."):
            st.session_state[f"{key}_clipgdf"] = v
        g = vs[v].to_crs(vs[v].estimate_utm_crs())
        st.caption(f"{v}: {len(g)} feature(s), {g.area.sum() / 1e6:,.1f} km².")
    if bbox:
        st.caption(f"Bounding box (lon/lat): {bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}")
    return bbox, template


def render(ctx, R):
    ui.section("🌍", "Download imagery and base layers", "Microsoft Planetary Computer: Sentinel-2 / Landsat cloud-free composites, Copernicus DEM, ESA WorldCover", "green")
    st.caption("Only the area of interest is read from the cloud-optimised files. Larger areas need coarser pixels: the limit is "
               f"{I.MAX_PIXELS:,} pixels per band (about 30 × 30 km at 10 m, 90 × 90 km at 30 m, 180 × 180 km at 60 m).")
    bbox, template = _aoi(ctx, R, "img")
    if bbox is None and template is None:
        return
    cv = st.session_state.get("img_clipgdf")
    clip = ctx.__dict__.get("vectors", {}).get(cv) if cv else None

    ui.section("🛰️", "Cloud-free composite", "Per-pixel cloud and shadow masking, then the median of the clearest scenes", "blue")
    c = st.columns(4)
    product = c[0].selectbox("Sensor", list(I.PRODUCTS), key="img_prod")
    today = datetime.date.today()
    start = c[1].date_input("From", datetime.date(today.year - 1, 1, 1), key="img_start")
    end = c[2].date_input("To", datetime.date(today.year - 1, 12, 31), key="img_end")
    cloud = c[3].slider("Max scene cloud %", 0, 100, 30, key="img_cloud")
    c = st.columns(4)
    nsc = c[0].number_input("Scenes per footprint tile", 1, 20, 4, key="img_n",
                            help="Least-cloudy scenes are taken for EACH Landsat path/row or Sentinel-2 tile touching the area, so the whole basin is covered.")
    res = c[1].number_input("Pixel size (m)", 10.0, 300.0, float(I.PRODUCTS[product]["res"]), 10.0, key=f"img_res_{product}",
                            disabled=template is not None)
    stat = c[2].selectbox("Statistic", ["median", "mean"], key="img_stat")
    plats = None
    if product.startswith("Landsat"):
        plats = c[3].multiselect("Platforms", ["landsat-4", "landsat-5", "landsat-7", "landsat-8", "landsat-9"], default=["landsat-8", "landsat-9"], key="img_plat",
                                 help="Use Landsat 5 for 1984-2012 and 7 for 1999-2022 (SLC-off gaps after 2003 are masked).")
    cc = st.columns(2)
    strict = cc[0].checkbox("Strict cloud mask (reject every cloud flag, incl. buffers)", False, key="img_strict",
                            help="Off = snow-aware Landsat mask: keeps bright snow and glacier ice that Fmask often flags as medium-confidence cloud.")
    fill = cc[1].checkbox("Fill pixels flagged in every scene (glaciers, high peaks)", True, key="img_fill",
                          help="Pixels the cloud mask rejected in EVERY scene take the median of all valid observations. Over glaciers and peaks "
                               "above ~5 000 m Fmask flags permanent ice as cloud or cirrus in every scene; real clouds move between dates. "
                               "Filled pixels have observation count 0 in the _obs_count layer.")
    out = st.text_input("Output name", f"{'S2' if product.startswith('Sentinel') else 'Landsat'}_{start.year}_{end.year}_composite.tif", key=f"img_out_{product}_{start}_{end}")
    c = st.columns(2)
    if c[0].button("🔎 Search scenes"):
        try:
            sbbox = bbox or I.grid_bbox_lonlat(ctx.store.get(template).crs, ctx.store.get(template).transform, ctx.store.get(template).data.shape)
            _, rows = I.search_scenes(_client(), product, sbbox, start.isoformat(), end.isoformat(), cloud, plats)
            st.session_state.img_scenes = rows
        except Exception as e:  # noqa: BLE001
            st.session_state.img_scenes = None
            st.error(f"Search failed: {type(e).__name__}: {e}")
    if st.session_state.get("img_scenes") is not None:
        rows = st.session_state.img_scenes
        tiles = sorted({r["tile"] for r in rows})
        st.caption(f"{len(rows)} scenes found over {len(tiles)} footprint tile(s) ({', '.join(tiles)}); up to {int(nsc)} least-cloudy scenes per tile "
                   "will be combined.")
        if rows:
            st.dataframe(pd.DataFrame(rows).head(30), hide_index=True)
    if c[1].button("⬇️ Download composite", type="primary"):
        bar = st.progress(0.0, "Starting…")
        try:
            res_ = I.download_composite(ctx.store, _client(), product, bbox, start.isoformat(), end.isoformat(), cloud, int(nsc), res, template, out,
                                        progress=lambda f, msg: bar.progress(float(f), msg), statistic=stat, platforms=plats, clip=clip, strict_mask=strict, fill_gaps=fill)
            ctx.store.add(res_["output"], ctx.store.outputs[res_["output"]])
            ctx.store.add(res_["observation_count"], ctx.store.outputs[res_["observation_count"]])
            ctx.record("download_composite", {"product": product, "bbox": bbox, "template": template, "start": str(start), "end": str(end),
                                              "max_cloud": cloud, "scenes": int(nsc), "res": res}, f"{res_['output']} {res_['size']}")
            ctx.__dict__.setdefault("results", []).append(dict(tool="download_composite", args=dict(product=product), result=res_,
                                                               time=datetime.datetime.now().isoformat(timespec="seconds")))
            st.session_state.img_res = res_
            bar.progress(1.0, "Done")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            bar.empty()
            st.error(f"Download failed: {type(e).__name__}: {e}")
    r = st.session_state.get("img_res")
    if r:
        m = st.columns(4)
        m[0].metric("Scenes used", len(r["scenes_used"]), f"{len(r.get('footprint_tiles', []))} tile(s), {r['scenes_found']} found", delta_color="off")
        m[1].metric("Size", f"{r['size'][0]} × {r['size'][1]} px", f"{r['resolution_m']:.0f} m", delta_color="off")
        m[2].metric("Area with data", f"{r['pixels_with_data_pct']:.1f}%",
                    f"{r.get('clear_pct', r['pixels_with_data_pct']):.1f}% clear + {r.get('gap_filled_pct', 0):.1f}% gap-filled", delta_color="off")
        m[3].metric("Mean clear observations", f"{r['mean_observations']:.1f}")
        if r["output"] in ctx.store.rasters:
            _rgb(ctx.store.get(r["output"]))
            st.download_button(f"⬇️ {r['output']}", ctx.store.outputs[r["output"]], r["output"], "image/tiff", key="dl_img_comp")
        if r["pixels_with_data_pct"] < 90:
            st.warning(f"Only {r['pixels_with_data_pct']:.0f}% of the area has a clear observation. Widen the dates, raise the cloud limit or the "
                       "scenes per tile.")
        if r.get("mask_rejections_pct"):
            st.caption("Why pixels were rejected by the cloud mask (share of all rejected scene-pixels): "
                       + ", ".join(f"{k} {v:.0f}%" for k, v in r["mask_rejections_pct"].items()))
        st.success(f"Added to the session layers. In 🛰️ Classification choose **{r['output']}** with preset **{r['preset']}**.")
        st.caption(r["note"])

    ui.section("⛰️", "Base layers on the same grid", "Copernicus DEM GLO-30 and ESA WorldCover land cover", "orange")
    st.caption("Tip: choose 'Extent and grid of a loaded raster' above with your composite or LULC map, so every layer lines up pixel for pixel.")
    c = st.columns(3)
    dres = c[0].number_input("DEM pixel size (m)", 10.0, 300.0, 30.0, 10.0, key="img_dres", disabled=template is not None)
    wyear = c[1].selectbox("WorldCover year", [2021, 2020], key="img_wy")
    wres = c[2].number_input("WorldCover pixel size (m)", 10.0, 300.0, 10.0, 10.0, key="img_wres", disabled=template is not None)
    c = st.columns(2)
    if c[0].button("⬇️ Download DEM"):
        try:
            d = I.download_dem(ctx.store, _client(), bbox, template, dres, clip=clip)
            ctx.store.add(d["output"], ctx.store.outputs[d["output"]])
            ctx.record("download_dem", {"bbox": bbox, "template": template}, d["output"])
            ctx.__dict__.setdefault("results", []).append(dict(tool="download_dem", args={}, result=d, time=datetime.datetime.now().isoformat(timespec="seconds")))
            st.session_state.img_dem = d
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"DEM download failed: {type(e).__name__}: {e}")
    if c[1].button("⬇️ Download WorldCover"):
        try:
            w = I.download_worldcover(ctx.store, _client(), bbox, template, wres, wyear, clip=clip)
            ctx.store.add(w["output"], ctx.store.outputs[w["output"]])
            ctx.record("download_worldcover", {"bbox": bbox, "template": template, "year": wyear}, w["output"])
            ctx.__dict__.setdefault("results", []).append(dict(tool="download_worldcover", args={"labels": w["labels"]}, result=w,
                                                               time=datetime.datetime.now().isoformat(timespec="seconds")))
            st.session_state.img_wc = w
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"WorldCover download failed: {type(e).__name__}: {e}")
    d, w = st.session_state.get("img_dem"), st.session_state.get("img_wc")
    if d:
        st.markdown(f"**{d['output']}**: {d['size'][0]} × {d['size'][1]} px, {d['min_m']:.0f}–{d['max_m']:.0f} m, coverage {d['coverage_pct']:.1f}%. {d['note']}")
    if w:
        st.markdown(f"**{w['output']}**")
        st.dataframe(pd.DataFrame({"class": list(w["class_area_ha"]), "area_ha": list(w["class_area_ha"].values())}), hide_index=True)
        st.caption(w["note"] + " Class names: " + ", ".join(f"{k} {v}" for k, v in w["labels"].items()))


def _rgb(r):
    import matplotlib.pyplot as plt
    import numpy as np
    b = r.bands
    if b is None or b.shape[0] < 3:
        return
    rgb = np.stack([b[2], b[1], b[0]], -1).astype(float)
    valid = ~r.mask
    lo, hi = np.percentile(rgb[valid], 2), np.percentile(rgb[valid], 98)
    img = np.clip((rgb - lo) / max(hi - lo, 1), 0, 1)
    img[~valid] = 1
    step = max(1, int(max(img.shape[:2]) / 900))
    fig, ax = plt.subplots(figsize=(6.4, 6.4 * img.shape[0] / img.shape[1]), dpi=110)
    ax.imshow(img[::step, ::step])
    ax.set_axis_off()
    ax.set_title("True-colour preview (2-98 % stretch)", fontsize=9)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
