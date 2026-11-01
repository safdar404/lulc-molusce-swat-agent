"""Streamlit app: LULC / MOLUSCE / SWAT+ research assistant (web version, no QGIS needed)."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

st.set_page_config(page_title="LULC-MOLUSCE-SWAT+ Agent", page_icon="🛰️", layout="wide")

try:
    import hydro, knowledge
    from agent import DEFAULT_MODEL, run_agent
    from session import Session
    __version__ = "0.2.1"
except ImportError as e:  # most common deployment mistake: folders flattened or missing dependencies
    st.error(f"Cannot import the analysis core: {e}")
    st.markdown("Check that all .py files from the flat package (metrics, knowledge, store, rasterops, hydro, session, agent_tools, agent) are in the same folder as app.py and that "
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
    st.title("🛰️ LULC Agent")
    st.caption(f"v{__version__} · experimental research tool")
    st.info("Files are processed in this browser session's memory and are not saved by the app. "
            "If you use the AI agent, tool results (statistics, not your rasters) are sent to the model provider. "
            "Do not upload confidential data you are not allowed to share.")
    rfiles = st.file_uploader("Rasters (GeoTIFF)", type=["tif", "tiff"], accept_multiple_files=True)
    for f in rfiles or []:
        if f.name not in ctx.store.rasters:
            try:
                ctx.store.add(f.name, f.getvalue())
            except Exception as e:
                st.error(f"{f.name}: {e}")
    tfiles = st.file_uploader("Tables (CSV): validation points, discharge", type=["csv"], accept_multiple_files=True)
    for f in tfiles or []:
        if f.name not in ctx.tables:
            try:
                ctx.tables[f.name] = pd.read_csv(f)
            except Exception as e:
                st.error(f"{f.name}: {e}")
    if st.button("Clear session"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:  # no secrets.toml configured
        key = ""
    key = key or st.text_input("Anthropic API key (for the Agent tab)", type="password")
    model = st.text_input("Model", DEFAULT_MODEL)

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


def download_outputs():
    for n, b in ctx.store.outputs.items():
        st.download_button(f"Download {n}", b, file_name=n, mime="image/tiff", key=f"dl_{n}")


tabs = st.tabs(["Guide", "Inspect and geometry", "Area and transitions", "Accuracy", "Hindcast", "Hydrology", "Agent", "Log"])

# ---------------- Guide ----------------
with tabs[0]:
    st.subheader("30-practical workflow")
    st.caption("Observe, classify, explain change, simulate, quantify hydrological consequences. A future map is a scenario, not a fact.")
    n = st.selectbox("Practical", list(knowledge.PRACTICALS), format_func=lambda i: f"{i}. {knowledge.PRACTICALS[i][0]}")
    t, d, v = knowledge.PRACTICALS[n]
    st.markdown(f"**Deliverable:** {d}\n\n**Viva question:** {v}")
    st.table(pd.DataFrame([(i, p[0], p[1]) for i, p in knowledge.PRACTICALS.items()], columns=["#", "Practical", "Deliverable"]))
    st.warning("This app does not run MOLUSCE's ANN/CA or QSWAT+. Run those in QGIS, then bring results here to evaluate them.")

# ---------------- Inspect ----------------
with tabs[1]:
    if need(R, "GeoTIFF rasters"):
        a = st.selectbox("Inspect raster", R)
        res = ctx.call("inspect_raster", {"layer": a})
        if show(res):
            st.json(res)
        st.subheader("MOLUSCE geometry check")
        sel = st.multiselect("Reference raster first, then others", R, default=R[:2] if len(R) > 1 else R)
        if len(sel) > 1 and st.button("Run geometry check"):
            res = ctx.call("check_geometry_match", {"layers": sel})
            if show(res):
                (st.success if res["all_match"] else st.error)("All rasters match the reference grid." if res["all_match"] else "Mismatch found: align rasters before MOLUSCE.")
                st.dataframe(pd.DataFrame(res["results"]))
        st.subheader("Spectral index")
        c = st.columns(5)
        idx = c[0].selectbox("Index", ["NDVI", "NDWI", "NDBI"])
        ba, bb = c[1].selectbox("First operand (NIR/Green/SWIR)", R), c[2].selectbox("Second operand (Red/NIR)", R)
        on = c[3].text_input("Output name", f"{idx}.tif")
        if c[4].button("Create"):
            res = ctx.call("spectral_index", {"index": idx, "band_a": ba, "band_b": bb, "output_name": on})
            show(res)
        download_outputs()

# ---------------- Area / transitions ----------------
with tabs[2]:
    if need(R, "LULC rasters"):
        a = st.selectbox("LULC raster", R, key="area_r")
        labels = st.text_input('Optional class names as JSON, e.g. {"1": "Water", "2": "Built-up"}')
        if st.button("Compute area statistics"):
            try:
                lab = json.loads(labels) if labels.strip() else None
            except Exception:
                lab = None
                st.warning("Could not read the class-name JSON; showing codes only.")
            res = ctx.call("lulc_area_stats", {"layer": a, "labels": lab})
            if show(res):
                df = pd.DataFrame(res["classes"])
                st.dataframe(df)
                st.bar_chart(df.set_index("code")["area_ha"])
                st.caption(f"Total {res['total_ha']:.1f} ha; pixel area {res['pixel_area_m2']} m².")
        if len(R) > 1:
            st.subheader("Transition matrix")
            c = st.columns(2)
            old, new = c[0].selectbox("Earlier", R, key="t_old"), c[1].selectbox("Later", R, index=1, key="t_new")
            if st.button("Compute transitions"):
                res = ctx.call("transition_matrix", {"old_layer": old, "new_layer": new})
                if show(res):
                    st.dataframe(pd.DataFrame(res["matrix_ha"], index=[f"old {k}" for k in res["classes"]], columns=[f"new {k}" for k in res["classes"]]))
                    st.metric("Persistence (%)", f"{res['persistence_percent']:.1f}")
                    st.dataframe(pd.DataFrame(res["top_conversions"]))
                    st.caption(res["note"])
            if st.button("Create transition raster (old×10+new)"):
                show(ctx.call("transition_raster", {"old_layer": old, "new_layer": new, "output_name": f"transition_{old}_{new}.tif"}))
            download_outputs()

# ---------------- Accuracy ----------------
with tabs[3]:
    if need(R, "a classified raster") and need(T, "a validation CSV (columns: x, y, reference class)"):
        a = st.selectbox("Classified raster", R, key="acc_r")
        tb = st.selectbox("Validation table", T)
        cols = list(ctx.tables[tb].columns)
        c = st.columns(4)
        rc, xc, yc = c[0].selectbox("Reference column", cols), c[1].selectbox("X column", cols), c[2].selectbox("Y column", cols, index=min(1, len(cols) - 1))
        epsg = c[3].number_input("Point EPSG (0 = same as raster)", 0, 99999, 0)
        if st.button("Assess accuracy"):
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

# ---------------- Hindcast ----------------
with tabs[4]:
    if need(R, "observed and simulated LULC rasters") and len(R) > 1:
        c = st.columns(3)
        ob, si = c[0].selectbox("Observed", R, key="h_o"), c[1].selectbox("Simulated", R, index=1, key="h_s")
        ini = c[2].selectbox("Initial map (optional)", ["(none)"] + R)
        if st.button("Validate hindcast"):
            res = ctx.call("hindcast_validation", {"observed": ob, "simulated": si, "initial": None if ini == "(none)" else ini})
            if show(res):
                m = st.columns(4)
                m[0].metric("Overall agreement", f"{res['overall_accuracy']:.3f}")
                m[1].metric("Kappa", f"{res['kappa']:.3f}")
                m[2].metric("Quantity disagreement", f"{res['disagreement']['quantity']:.3f}")
                m[3].metric("Allocation disagreement", f"{res['disagreement']['allocation']:.3f}")
                if "figure_of_merit" in res:
                    st.json(res["figure_of_merit"])
                st.caption(res["interpretation_note"])
        if st.button("Create disagreement raster"):
            show(ctx.call("disagreement_raster", {"observed": ob, "simulated": si, "output_name": f"disagreement_{ob}_{si}.tif"}))
        download_outputs()

# ---------------- Hydrology ----------------
with tabs[5]:
    if need(T, "observed and simulated discharge CSV files"):
        c = st.columns(2)
        ot, stb = c[0].selectbox("Observed table", T, key="ho"), c[1].selectbox("Simulated table", T, key="hs", index=min(1, len(T) - 1))
        dcol = st.selectbox("Date column", list(ctx.tables[ot].columns))
        c = st.columns(2)
        oc, sc = c[0].selectbox("Observed column", list(ctx.tables[ot].columns)), c[1].selectbox("Simulated column", list(ctx.tables[stb].columns))
        c = st.columns(2)
        s0, s1 = c[0].text_input("Start date (optional, YYYY-MM-DD)"), c[1].text_input("End date (optional)")
        if st.button("Compute hydrological metrics"):
            res = ctx.call("hydro_metrics", {"observed_table": ot, "simulated_table": stb, "date_column": dcol, "observed_column": oc,
                                             "simulated_column": sc, "start": s0 or None, "end": s1 or None})
            if show(res):
                m = st.columns(5)
                for col, k in zip(m, ["n_pairs", "nse", "pbias_percent", "r2", "kge"]):
                    col.metric(k.upper(), f"{res[k]:.3f}" if isinstance(res[k], float) else res[k])
                st.line_chart(hydro.align(ctx.tables[ot], ctx.tables[stb], dcol, oc, sc, s0 or None, s1 or None).set_index("date")[["obs", "sim"]])
                st.caption(res["caution"])

# ---------------- Agent ----------------
with tabs[6]:
    st.caption("The agent calls the same audited tools as the other tabs. It cannot run MOLUSCE or QSWAT+.")
    for role, text in st.session_state.chat:
        with st.chat_message("assistant" if role in ("assistant", "tool", "error") else "user"):
            st.markdown(f"`{text}`" if role == "tool" else text)
    q = st.chat_input("Ask about your data or the workflow...")
    if q:
        if not key:
            st.error("Enter your API key in the sidebar first.")
        else:
            st.session_state.chat.append(("user", q))
            with st.spinner("Working..."):
                try:
                    st.session_state.chat += run_agent(key, model, st.session_state.msgs, ctx, q)
                except Exception as e:
                    st.session_state.chat.append(("error", f"{type(e).__name__}: {str(e)[:300]}"))
            st.rerun()

# ---------------- Log ----------------
with tabs[7]:
    df = ctx.log_df()
    st.dataframe(df)
    if len(df):
        st.download_button("Download processing log (CSV)", df.to_csv(index=False), "processing_log.csv", "text/csv")
