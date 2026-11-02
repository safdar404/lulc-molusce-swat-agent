"""🛰️ Live map canvas tab: real-time processing monitor + export-ready cartographic map composer."""
import json
import time

import pandas as pd
import streamlit as st

import cartography
import live
import ui

MONITOR_CSS = """
<style>
.monitor-head{display:flex;align-items:center;gap:.55rem;background:#0b1220;color:#d6e4ff;border-radius:14px 14px 0 0;
  padding:.45rem .9rem;font:600 .82rem ui-monospace,Menlo,monospace;letter-spacing:.03em}
.monitor-head .dot{width:.6rem;height:.6rem;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e}
.monitor-head .dot.idle{background:#64748b;box-shadow:none}
.monitor-log{background:#0b1220;color:#9fe3b5;font:12px/1.45 ui-monospace,Menlo,monospace;border-radius:10px;padding:.6rem .8rem;
  max-height:230px;overflow:auto;white-space:pre-wrap}
</style>"""


def _img(target, img, caption=None):
    try:
        target.image(img, caption=caption, width="stretch")
    except Exception:  # older Streamlit
        target.image(img, caption=caption, use_container_width=True)


def _labels(text):
    if not text.strip():
        return {}
    try:
        d = json.loads(text)
        return {str(k): str(v) for k, v in d.items()}
    except Exception:
        st.warning("Could not read the class-name JSON; class codes are used instead.")
        return {}


def _head(target, text, active):
    target.markdown(f'<div class="monitor-head"><span class="dot{"" if active else " idle"}"></span>{text}</div>', unsafe_allow_html=True)


def _stats_df(stats, labels):
    cls = stats.get("classes")
    if not cls:
        return None
    tot = sum(cls.values()) or 1
    return pd.DataFrame([(labels.get(str(k), f"Class {k}"), v, round(v / tot * 100, 2)) for k, v in cls.items()],
                        columns=["class", stats.get("unit", "value"), "%"])


def render(ctx, version):
    st.markdown(MONITOR_CSS, unsafe_allow_html=True)
    layers = ctx.store.names() + [n for n in ctx.store.outputs if n not in ctx.store.rasters]
    ss = st.session_state

    # ---------------- 1. live processing monitor ----------------
    ui.section("🛰️", "Live processing monitor", "Processes the raster strip by strip at full resolution and draws the result on the canvas as it is computed", "blue")
    if not layers:
        st.info("Upload GeoTIFF rasters in the sidebar (satellite bands, LULC maps, MOLUSCE outputs, DEM) to use the live canvas.")
        return
    c = st.columns([2, 1, 1])
    op = c[0].selectbox("Analysis", live.OPERATIONS, key="lv_op")
    blocks = c[1].slider("Processing blocks", 4, 64, 16, help="Number of strips the raster is processed in; the canvas refreshes after each one.")
    pace = c[2].slider("Display pace (s/block)", 0.0, 0.5, 0.08, 0.02, help="Pause between canvas refreshes so you can follow the scan. It does not change any result.")

    needs = {"Classified LULC map": ["LULC raster"], "Spectral index (NDVI / NDWI / NDBI)": ["First operand (NIR / Green / SWIR)", "Second operand (Red / NIR)"],
             "LULC change (from → to)": ["Earlier LULC", "Later LULC"], "Hindcast disagreement (observed vs simulated)": ["Observed LULC", "Simulated LULC"],
             "Satellite RGB composite": ["Red channel band", "Green channel band", "Blue channel band"], "Continuous raster (DEM, band, index)": ["Raster"]}[op]
    c = st.columns(len(needs) + (1 if op.startswith("Spectral") else 0))
    picks = [c[i].selectbox(lbl, layers, index=min(i, len(layers) - 1), key=f"lv_in_{op}_{i}") for i, lbl in enumerate(needs)]
    index = c[-1].selectbox("Index", ["NDVI", "NDWI", "NDBI"], key="lv_idx") if op.startswith("Spectral") else None
    if op.startswith("Satellite"):
        st.caption("True colour: Red, Green, Blue bands (Landsat 8/9 B4-B3-B2, Sentinel-2 B4-B3-B2). False colour vegetation: NIR, Red, Green.")
    lab_txt = ""
    if op in ("Classified LULC map", "LULC change (from → to)"):
        lab_txt = st.text_input('Class names as JSON (used on the canvas, legend and map), e.g. {"1": "Water", "2": "Built-up", "3": "Vegetation"}', key="lv_lab")
        st.caption("With class names such as Water, Built-up, Forest, Agriculture, Bare soil, the canvas and map use conventional LULC colours; without them colours are arbitrary.")

    run = st.button("▶️ Run live analysis", type="primary")

    left, right = st.columns([3, 2])
    head, canvas = left.empty(), left.empty()
    rhead, prog, mrow, table, logbox = right.empty(), right.empty(), right.empty(), right.empty(), right.empty()

    if run:
        labels = _labels(lab_txt)
        try:
            job = live.build(ctx.store, op, picks, index=index or "NDVI", labels=labels)
            style = live.frame_style(job, [ctx.store.get(n) for n in picks])
        except Exception as e:
            st.error(str(e))
            return
        lines = [f"[{time.strftime('%H:%M:%S')}] START  {op}", f"           inputs: {', '.join(picks)}",
                 f"           grid: {job.mask.shape[1]} × {job.mask.shape[0]} px · CRS {job.crs.to_string() if job.crs else 'none'}"]
        _head(rhead, "MONITOR · running", True)
        t0 = time.time()
        for j in live.run(job, blocks):
            pct = j.rows_done / j.rows
            _head(head, f"LIVE CANVAS · {op} · {pct * 100:5.1f}%", True)
            _img(canvas, cartography.preview_frame(j.arr, j.mask, j.rows_done, kind=j.kind, **style))
            prog.progress(pct, text=f"Rows {j.rows_done:,} / {j.rows:,}")
            stt = j.stats()
            with mrow.container():
                m = st.columns(3)
                m[0].metric("Processed", f"{pct * 100:.0f}%")
                vp = stt.get("valid pixels", 0)
                m[1].metric("Valid pixels", f"{vp / 1e6:.2f} M" if vp >= 1e6 else f"{vp / 1e3:.1f} k" if vp >= 1e4 else f"{vp:,}")
                key3 = next((k for k in ("changed %", "disagreement %", "mean") if k in stt), None)
                m[2].metric(key3 or "Elapsed (s)", stt[key3] if key3 else f"{time.time() - t0:.1f}")
            df = _stats_df(stt, job.labels)
            if df is not None:
                table.dataframe(df, hide_index=True)
            lines.append(f"[{time.strftime('%H:%M:%S')}] block → rows {j.rows_done:>6}  " +
                         ("  ".join(f"{k}={v}" for k, v in stt.items() if k not in ("classes", "rows", "unit")))[:110])
            logbox.markdown(f'<div class="monitor-log">{chr(10).join(lines[-14:])}</div>', unsafe_allow_html=True)
            if pace:
                time.sleep(pace)
        lines.append(f"[{time.strftime('%H:%M:%S')}] DONE   in {time.time() - t0:.2f} s · composing map layout…")
        logbox.markdown(f'<div class="monitor-log">{chr(10).join(lines[-14:])}</div>', unsafe_allow_html=True)
        out = job.geotiff()
        if out is not None and job.op not in ("Classified LULC map", "Continuous raster (DEM, band, index)"):
            ctx.store.outputs[job.out_name] = out
        title = {"LULC (classified)": "Land Use / Land Cover", "Change / transition": "LULC Change (from → to)",
                 "Disagreement": "Hindcast Disagreement: Observed vs Simulated", "Spectral index": f"{job.index_name} Map",
                 "RGB composite": "Satellite Image Composite", "Continuous": picks[0]}[job.kind]
        ss.map_cfg = dict(source="Last live result", title=title, subtitle=" vs ".join(picks) if len(picks) > 1 else picks[0])
        ss.live_job = job
        ss.live_log = lines
        ss.live_final = cartography.preview_frame(job.arr, job.mask, job.rows, kind=job.kind, **style)
        ss.map_png = None
        ss.mp_src = "Last live result"  # point the composer at the new result and reset its per-layer fields
        for k in [k for k in ss.keys() if str(k).endswith("_Last live result")]:
            del ss[k]
        ctx.record("live_canvas", {"operation": op, "inputs": picks, "blocks": blocks, "index": index},
                   output=job.out_name if out is not None else "map only", note="Live canvas run; map composed below.")
        prog.progress(1.0, text="Complete")
        _head(rhead, "MONITOR · complete", False)
        st.success("Analysis complete. The finished map layout is below." + (f" GeoTIFF saved as **{job.out_name}** (download below)." if job.out_name in ctx.store.outputs else ""))
    elif "live_final" in ss:
        _head(head, "LIVE CANVAS · last run", False)
        _img(canvas, ss.live_final)
        _head(rhead, "MONITOR · idle", False)
        logbox.markdown(f'<div class="monitor-log">{chr(10).join(ss.live_log[-14:])}</div>', unsafe_allow_html=True)
    else:
        _head(head, "LIVE CANVAS · idle — choose an analysis and press Run", False)
        _head(rhead, "MONITOR · idle", False)

    # ---------------- 2. map composer ----------------
    st.write("")
    ui.section("🗺️", "Map layout (export-ready)", "Title, legend, scale bar, north arrow, grid coordinates and metadata box — ready for a thesis or report", "green")
    cfg = ss.get("map_cfg", {})
    sources = (["Last live result"] if "live_job" in ss else []) + layers
    c = st.columns([2, 2, 1])
    if ss.get("mp_src") not in sources:
        ss.mp_src = sources[0]
    src = c[0].selectbox("Layer to map", sources, key="mp_src")
    if src == "Last live result":
        j = ss.live_job
        arr, mask, tr, crs, auto_kind, lab0, idx_name = j.arr, j.mask, j.transform, j.crs, j.kind, j.labels, j.index_name
    else:
        r = ctx.store.get(src)
        arr, mask, tr, crs, lab0, idx_name = r.data, r.mask, r.transform, r.crs, {}, None
        auto_kind = cartography.guess_kind(arr, mask, src)
        idx_name = next((k for k in ("NDVI", "NDWI", "NDBI") if k.lower() in src.lower()), None)
    kinds = [k for k in cartography.MAP_KINDS if (k == "RGB composite") == (arr.ndim == 3)]
    kind = c[1].selectbox("Map type", kinds, index=kinds.index(auto_kind) if auto_kind in kinds else 0, key=f"mp_kind_{src}")
    dpi = c[2].selectbox("Export DPI", [150, 200, 300, 600], index=2)

    c = st.columns(2)
    title = c[0].text_input("Map title", cfg.get("title", src) if src == cfg.get("source") else src.rsplit(".", 1)[0], key=f"mp_t_{src}")
    subtitle = c[1].text_input("Subtitle (study area, year)", cfg.get("subtitle", "") if src == cfg.get("source") else "", key=f"mp_s_{src}")
    c = st.columns(3)
    author = c[0].text_input("Author", key="mp_author")
    source = c[1].text_input("Data source", "Landsat / Sentinel-2 derived (user GeoTIFF)", key="mp_source")
    ramp = None
    if kind in ("Spectral index", "Continuous"):
        opts = ["RdYlGn", "viridis", "terrain", "BrBG", "Spectral", "magma", "Blues", "YlOrBr"]
        default = cartography.CONTINUOUS.get(idx_name or ("DEM" if kind == "Continuous" else ""), "viridis")
        ramp = c[2].selectbox("Colour ramp", opts, index=opts.index(default) if default in opts else 1, key=f"mp_ramp_{src}")
        idx_name = idx_name or c[2].text_input("Value label", "Value", key="mp_vl")
    lab_txt = ""
    if kind == "LULC (classified)" and src != "Last live result":
        lab_txt = st.text_input('Class names as JSON, e.g. {"1": "Water", "2": "Built-up", "3": "Vegetation", "4": "Agriculture", "5": "Bare soil"}', key=f"mp_lab_{src}")
    c = st.columns(4)
    grid, north = c[0].checkbox("Grid coordinates", True), c[1].checkbox("North arrow", True)
    scale, lstats = c[2].checkbox("Scale bar", True), c[3].checkbox("Area / % in legend", True)

    if st.button("🖨️ Compose map", type="primary") or (ss.get("map_png") is None and "live_job" in ss and src == "Last live result"):
        labels = {**lab0, **_labels(lab_txt)}
        with st.spinner("Composing map layout…"):
            try:
                kw = dict(kind=kind, title=title, subtitle=subtitle, labels=labels, layer_name=src if src != "Last live result" else ss.live_job.out_name,
                          index_name=idx_name, cmap=ramp, author=author, source=source, show_grid=grid, show_north=north,
                          show_scale=scale, legend_stats=lstats, version=version)
                ss.map_png = cartography.fig_bytes(cartography.compose_map(arr, mask, tr, crs, **kw), "png", dpi)
                ss.map_pdf = cartography.fig_bytes(cartography.compose_map(arr, mask, tr, crs, **kw), "pdf", dpi)
                ss.map_name = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_") or "map"
                ctx.record("compose_map", {"layer": src, "kind": kind, "title": title, "dpi": dpi}, output=f"{ss.map_name}.png/.pdf")
            except Exception as e:
                st.error(f"Could not compose the map: {e}")
                ss.map_png = None
    if ss.get("map_png"):
        _img(st, ss.map_png)
        c = st.columns(3)
        c[0].download_button("⬇️ Map PNG", ss.map_png, f"{ss.map_name}.png", "image/png")
        c[1].download_button("⬇️ Map PDF (print)", ss.map_pdf, f"{ss.map_name}.pdf", "application/pdf")
        if "live_job" in ss and ss.live_job.out_name in ctx.store.outputs:
            c[2].download_button(f"⬇️ GeoTIFF {ss.live_job.out_name}", ctx.store.outputs[ss.live_job.out_name], ss.live_job.out_name, "image/tiff")
        st.caption("Check before submitting: class names and colours, title/year, data source, and that the scale bar unit suits the map extent. "
                   "Grid north is shown; for geographic CRS the scale bar is approximate at the map centre.")
