"""Streamlit app: LULC / MOLUSCE / SWAT+ research assistant (web version, no QGIS needed)."""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import importlib  # noqa: E402

# Streamlit re-runs app.py when it changes but keeps helper modules cached. After a multi-file update that leaves
# a stale mix (e.g. "cannot import name ... from 'agent'"), so reload every local module whose file changed.
_LOCAL_MODULES = ["metrics", "knowledge", "store", "rasterops", "olofsson", "intensity", "changeops", "landscape", "hotspot", "patternops", "classify", "simulate", "swatlink", "vectorops", "imagery", "jobs", "cryo", "cartography", "report", "app_version", "hydro", "session", "agent_tools", "agent", "ui", "advanced_tabs", "pattern_tab", "classify_tab", "simulate_tab", "swat_tab", "vector_tab", "imagery_tab", "cryo_tab", "report_tab", "live", "canvas_tab"]  # dependency order
for _name in _LOCAL_MODULES:
    _mod = sys.modules.get(_name)
    if _mod is not None and getattr(_mod, "__file__", None):
        try:
            if getattr(_mod, "_file_mtime", None) != Path(_mod.__file__).stat().st_mtime:
                importlib.reload(_mod)
        except Exception:
            pass

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import ui  # noqa: E402

st.set_page_config(page_title="LULC-MOLUSCE-SWAT+ Agent", page_icon=ui.page_icon(), layout="wide")
ui.apply_theme()

try:
    import advanced_tabs, app_version, canvas_tab, classify_tab, cryo_tab, hydro, imagery_tab, knowledge, pattern_tab, report_tab, simulate_tab, swat_tab, vector_tab, vectorops
    from agent import DEFAULT_MODEL, friendly_error, offline_analysis, run_agent
    from session import Session
    __version__ = app_version.VERSION
    for _name in _LOCAL_MODULES:
        _mod = sys.modules.get(_name)
        if _mod is not None and getattr(_mod, "__file__", None):
            _mod._file_mtime = Path(_mod.__file__).stat().st_mtime
except ImportError as e:  # most common deployment mistake: folders flattened or missing dependencies
    st.error(f"Cannot import the analysis core: {e}")
    st.markdown("Check that all .py files from the flat package (metrics, knowledge, store, rasterops, olofsson, intensity, changeops, landscape, hotspot, patternops, classify, simulate, swatlink, vectorops, imagery, cryo, report, hydro, session, agent_tools, agent, advanced_tabs, pattern_tab, classify_tab, simulate_tab, swat_tab, vector_tab, report_tab) are in the same folder as app.py and that "
                "`requirements.txt` was installed. ")
    st.stop()


def get_ctx() -> Session:
    if "ctx" not in st.session_state:
        st.session_state.ctx = Session()
        st.session_state.chat, st.session_state.msgs = [], []
    return st.session_state.ctx


ctx = get_ctx()

# ---------------- sidebar ----------------
with st.sidebar:
    brand = st.empty()
    st.info("Files are processed in this browser session's memory and are not saved by the app. "
            "If you use the AI agent, tool results (statistics, not your rasters) are sent to the model provider. "
            "Do not upload confidential data you are not allowed to share.")
    rfiles = st.file_uploader("🗺️ Rasters (GeoTIFF)", type=["tif", "tiff"], accept_multiple_files=True)
    for f in rfiles or []:
        if f.name not in ctx.store.rasters:
            try:
                ctx.store.add(f.name, f.getvalue())
            except Exception as e:
                st.error(f"{f.name}: {e}")
    tfiles = st.file_uploader("📊 Tables (CSV): validation points, discharge", type=["csv"], accept_multiple_files=True)
    for f in tfiles or []:
        if f.name not in ctx.tables:
            try:
                ctx.tables[f.name] = pd.read_csv(f)
            except Exception as e:
                st.error(f"{f.name}: {e}")
    vfiles = st.file_uploader("🧭 Vectors: zipped shapefile, GeoPackage, GeoJSON, KML", type=[e.strip(".") for e in vectorops.VECTOR_EXT],
                              accept_multiple_files=True)
    seen = ctx.__dict__.setdefault("vector_files", set())
    new_v = {f.name: f.getvalue() for f in vfiles or [] if f.name not in seen}
    if new_v:
        try:
            ctx.__dict__.setdefault("vectors", {}).update(vectorops.read_vector(new_v))
            seen |= set(new_v)
        except Exception as e:
            st.error(f"Vector upload: {e}")
    with brand.container():
        ui.sidebar_brand(__version__, len(ctx.store.rasters), len(ctx.tables), len(ctx.store.outputs))
    if st.button("🧹 Clear session"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:  # no secrets.toml configured
        key = ""
    key = key or st.text_input("🔑 Anthropic API key (for the Agent tab)", type="password")
    model = st.text_input("🧠 Model", DEFAULT_MODEL)

ui.hero(__version__)

R, T = ctx.store.names(), list(ctx.tables)


def need(items, what):
    if not items:
        st.info(f"Upload {what} in the sidebar to use this tab.")
        return False
    return True


def show(res):
    if "error" in res:
        st.error(res["error"])
        return False
    return True


def download_outputs(where):
    for n, b in ctx.store.outputs.items():
        st.download_button(f"⬇️ Download {n}", b, file_name=n, mime="image/tiff", key=f"dl_{where}_{n}")


tabs = st.tabs(["📚 Guide", "🛰️ Live map canvas", "🌍 Download imagery", "🏔️ Snow, ice & elevation", "🔍 Inspect & geometry", "🧭 Vector tools", "🛰️ Classification", "🗺️ Area & transitions", "📈 Intensity analysis", "🧩 Landscape & hotspots", "🔮 Drivers & scenarios", "🎯 Accuracy",
                "📏 Area-adjusted accuracy", "⏪ Hindcast", "💧 Hydrology", "🌊 SWAT+ link", "🤖 Agent", "📝 Log & report"])

# ---------------- Guide ----------------
with tabs[0]:
    ui.section("📚", "30-practical workflow", "Observe, classify, explain change, simulate, quantify hydrological consequences. A future map is a scenario, not a fact.", "violet")
    ui.workflow_strip()
    n = st.selectbox("Practical", list(knowledge.PRACTICALS), format_func=lambda i: f"{i}. {knowledge.PRACTICALS[i][0]}")
    t, d, v = knowledge.PRACTICALS[n]
    ui.practical_card(n, t, d, v)
    st.write("")
    st.dataframe(pd.DataFrame([(i, p[0], p[1]) for i, p in knowledge.PRACTICALS.items()], columns=["#", "Practical", "Deliverable"]), hide_index=True)
    st.info("**How this fits your workflow:** run MOLUSCE (ANN / cellular automata) and QSWAT+ in QGIS as usual, then upload their outputs here "
            "to check raster geometry, validate the hindcast (kappa, figure of merit) and score SWAT+ runs (NSE, PBIAS, KGE).", icon="🧭")

# ---------------- Live map canvas ----------------
with tabs[1]:
    canvas_tab.render(ctx, __version__)

# ---------------- Download imagery ----------------
with tabs[2]:
    imagery_tab.render(ctx, R)

# ---------------- Snow, ice & elevation ----------------
with tabs[3]:
    cryo_tab.render(ctx, R)

# ---------------- Inspect ----------------
with tabs[4]:
    if need(R, "GeoTIFF rasters"):
        ui.section("🔍", "Inspect raster", "CRS, size, pixel size, origin, NoData and class values", "blue")
        a = st.selectbox("Inspect raster", R)
        res = ctx.call("inspect_raster", {"layer": a})
        if show(res):
            st.json(res)
        ui.section("📐", "MOLUSCE geometry check", "CRS, cell size, rows/columns, origin and NoData mask vs the reference grid", "green")
        sel = st.multiselect("Reference raster first, then others", R, default=R[:2] if len(R) > 1 else R)
        if len(sel) > 1 and st.button("📐 Run geometry check"):
            res = ctx.call("check_geometry_match", {"layers": sel})
            if show(res):
                (st.success if res["all_match"] else st.error)("All rasters match the reference grid." if res["all_match"] else "Mismatch found: align rasters before MOLUSCE.")
                st.dataframe(pd.DataFrame(res["results"]))
        ui.section("🌿", "Spectral index", "NDVI, NDWI or NDBI as a downloadable GeoTIFF", "orange")
        c = st.columns(5)
        idx = c[0].selectbox("Index", ["NDVI", "NDWI", "NDBI"])
        ba, bb = c[1].selectbox("First operand (NIR/Green/SWIR)", R), c[2].selectbox("Second operand (Red/NIR)", R)
        on = c[3].text_input("Output name", f"{idx}.tif")
        if c[4].button("🌿 Create"):
            res = ctx.call("spectral_index", {"index": idx, "band_a": ba, "band_b": bb, "output_name": on})
            show(res)
        download_outputs("inspect")

# ---------------- Vector tools ----------------
with tabs[5]:
    vector_tab.render(ctx, R)

# ---------------- Classification ----------------
with tabs[6]:
    classify_tab.render(ctx, R)

# ---------------- Area / transitions ----------------
with tabs[7]:
    if need(R, "LULC rasters"):
        ui.section("🗺️", "LULC area statistics", "Pixel counts, hectares and shares per class", "pink")
        a = st.selectbox("LULC raster", R, key="area_r")
        labels = st.text_input('Optional class names as JSON, e.g. {"1": "Water", "2": "Built-up"}')
        if st.button("📊 Compute area statistics"):
            try:
                lab = json.loads(labels) if labels.strip() else None
            except Exception:
                lab = None
                st.warning("Could not read the class-name JSON; showing codes only.")
            res = ctx.call("lulc_area_stats", {"layer": a, "labels": lab})
            if show(res):
                df = pd.DataFrame(res["classes"])
                st.dataframe(df, hide_index=True)
                df["class"] = df.apply(lambda r: f"{r['code']} {r['name'] or ''}".strip(), axis=1)
                ui.bar_chart(df, "class", "area_ha", "Area (ha)")
                st.caption(f"Total {res['total_ha']:.1f} ha; pixel area {res['pixel_area_m2']} m².")
        if len(R) > 1:
            ui.section("🔀", "Transition matrix", "From-to change (ha) between two dates on the same grid", "violet")
            c = st.columns(2)
            old, new = c[0].selectbox("Earlier", R, key="t_old"), c[1].selectbox("Later", R, index=1, key="t_new")
            if st.button("🔀 Compute transitions"):
                res = ctx.call("transition_matrix", {"old_layer": old, "new_layer": new})
                if show(res):
                    st.dataframe(pd.DataFrame(res["matrix_ha"], index=[f"old {k}" for k in res["classes"]], columns=[f"new {k}" for k in res["classes"]]))
                    st.metric("Persistence (%)", f"{res['persistence_percent']:.1f}")
                    st.dataframe(pd.DataFrame(res["top_conversions"]))
                    st.caption(res["note"])
            if st.button("🧩 Create transition raster (old×10+new)"):
                show(ctx.call("transition_raster", {"old_layer": old, "new_layer": new, "output_name": f"transition_{old}_{new}.tif"}))
            download_outputs("area")

# ---------------- Intensity analysis ----------------
with tabs[8]:
    advanced_tabs.render_intensity(ctx, R)

# ---------------- Landscape & hotspots ----------------
with tabs[9]:
    pattern_tab.render(ctx, R)

# ---------------- Drivers & scenarios ----------------
with tabs[10]:
    simulate_tab.render(ctx, R)

# ---------------- Accuracy ----------------
with tabs[11]:
    if need(R, "a classified raster") and need(T, "a validation CSV (columns: x, y, reference class)"):
        ui.section("🎯", "Accuracy assessment", "Confusion matrix, overall / user's / producer's accuracy and kappa", "orange")
        a = st.selectbox("Classified raster", R, key="acc_r")
        tb = st.selectbox("Validation table", T)
        cols = list(ctx.tables[tb].columns)
        c = st.columns(4)
        rc, xc, yc = c[0].selectbox("Reference column", cols), c[1].selectbox("X column", cols), c[2].selectbox("Y column", cols, index=min(1, len(cols) - 1))
        epsg = c[3].number_input("Point EPSG (0 = same as raster)", 0, 99999, 0)
        if st.button("🎯 Assess accuracy"):
            res = ctx.call("accuracy_assessment", {"raster": a, "table": tb, "reference_column": rc, "x_column": xc, "y_column": yc, "epsg": int(epsg) or None})
            if show(res):
                m = st.columns(3)
                m[0].metric("Overall accuracy", f"{res['overall_accuracy']:.3f}")
                m[1].metric("Kappa", f"{res['kappa']:.3f}")
                m[2].metric("Samples", res["n"])
                cl = [str(k) for k in res["classes"]]
                st.dataframe(pd.DataFrame(res["confusion_matrix_rows_reference_cols_predicted"], index=[f"ref {k}" for k in cl], columns=[f"pred {k}" for k in cl]))
                st.dataframe(pd.DataFrame({"class": cl, "producers_accuracy": res["producers_accuracy"], "users_accuracy": res["users_accuracy"]}))
                st.caption(res["warning"])

# ---------------- Area-adjusted accuracy ----------------
with tabs[12]:
    advanced_tabs.render_accuracy(ctx, R, T)

# ---------------- Hindcast ----------------
with tabs[13]:
    ui.section("⏪", "Hindcast validation", "Kappa, quantity / allocation disagreement and figure of merit", "pink")
    if len(R) < 2:
        st.info("Upload at least two LULC rasters (observed and simulated) in the sidebar to validate a hindcast.")
    else:
        c = st.columns(3)
        ob, si = c[0].selectbox("Observed", R, key="h_o"), c[1].selectbox("Simulated", R, index=1, key="h_s")
        ini = c[2].selectbox("Initial map (optional)", ["(none)"] + R)
        if st.button("⏪ Validate hindcast"):
            res = ctx.call("hindcast_validation", {"observed": ob, "simulated": si, "initial": None if ini == "(none)" else ini})
            if show(res):
                m = st.columns(4)
                m[0].metric("Overall agreement", f"{res['overall_accuracy']:.3f}")
                m[1].metric("Kappa", f"{res['kappa']:.3f}")
                m[2].metric("Quantity disagreement", f"{round(res['disagreement']['quantity'], 3) + 0.0:.3f}")
                m[3].metric("Allocation disagreement", f"{round(res['disagreement']['allocation'], 3) + 0.0:.3f}")
                if "figure_of_merit" in res:
                    st.json(res["figure_of_merit"])
                st.caption(res["interpretation_note"])
        if st.button("🗺️ Create disagreement raster"):
            show(ctx.call("disagreement_raster", {"observed": ob, "simulated": si, "output_name": f"disagreement_{ob}_{si}.tif"}))
        download_outputs("hindcast")

# ---------------- Hydrology ----------------
with tabs[14]:
    ui.section("💧", "Hydrological performance", "NSE, PBIAS, R² and KGE from observed vs simulated discharge", "blue")
    if need(T, "observed and simulated discharge CSV files"):
        c = st.columns(2)
        ot, stb = c[0].selectbox("Observed table", T, key="ho"), c[1].selectbox("Simulated table", T, key="hs", index=min(1, len(T) - 1))
        dcol = st.selectbox("Date column", list(ctx.tables[ot].columns))
        c = st.columns(2)
        ocols, scols = list(ctx.tables[ot].columns), list(ctx.tables[stb].columns)
        oc = c[0].selectbox("Observed column", ocols, index=min(1, len(ocols) - 1))
        sc = c[1].selectbox("Simulated column", scols, index=min(2 if stb == ot else 1, len(scols) - 1))
        c = st.columns(2)
        s0, s1 = c[0].text_input("Start date (optional, YYYY-MM-DD)"), c[1].text_input("End date (optional)")
        if st.button("💧 Compute hydrological metrics"):
            res = ctx.call("hydro_metrics", {"observed_table": ot, "simulated_table": stb, "date_column": dcol, "observed_column": oc,
                                             "simulated_column": sc, "start": s0 or None, "end": s1 or None})
            if show(res):
                m = st.columns(5)
                for col, k in zip(m, ["n_pairs", "nse", "pbias_percent", "r2", "kge"]):
                    col.metric(k.upper(), f"{res[k]:.3f}" if isinstance(res[k], float) else res[k])
                st.line_chart(hydro.align(ctx.tables[ot], ctx.tables[stb], dcol, oc, sc, s0 or None, s1 or None).set_index("date")[["obs", "sim"]], color=["#06B6D4", "#EC4899"])
                st.caption(res["caution"])

# ---------------- SWAT+ link ----------------
with tabs[15]:
    swat_tab.render(ctx, R)

# ---------------- Agent ----------------
with tabs[16]:
    ui.section("🤖", "Research agent", "Calls the same audited tools as the other tabs and evaluates MOLUSCE / QSWAT+ results you bring from QGIS.", "violet")
    for role, text in st.session_state.chat:
        is_user = role not in ("assistant", "tool", "error")
        with st.chat_message("user" if is_user else "assistant", avatar="🧑‍🔬" if is_user else ui.page_icon()):
            st.markdown(f"`{text}`" if role == "tool" else text)
    if not key:
        st.info("No API key set: answers come from the built-in analysis (no AI). Add an Anthropic key in the sidebar for the full agent.")
    if st.button("⚡ Quick analysis of loaded data (no AI needed)"):
        st.session_state.chat.append(("assistant", offline_analysis(ctx)))
        st.rerun()
    q = st.chat_input("Ask about your data or the workflow...")
    if q:
        st.session_state.chat.append(("user", q))
        if not key:
            st.session_state.chat.append(("assistant", offline_analysis(ctx)))
        else:
            with st.spinner("Working..."):
                try:
                    st.session_state.chat += run_agent(key, model, st.session_state.msgs, ctx, q)
                except Exception as e:
                    st.session_state.chat.append(("error", friendly_error(e)))
                    st.session_state.chat.append(("assistant", offline_analysis(ctx)))
        st.rerun()

# ---------------- Log ----------------
with tabs[17]:
    ui.section("📝", "Processing log", "Every tool call in the manual's template: date, input, tool version, parameters, output, note", "green")
    df = ctx.log_df()
    st.dataframe(df, hide_index=True)
    if len(df):
        st.download_button("⬇️ Download processing log (CSV)", df.to_csv(index=False), "processing_log.csv", "text/csv")
    report_tab.render(ctx, __version__)

ui.footer()
