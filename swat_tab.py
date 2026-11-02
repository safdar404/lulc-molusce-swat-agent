"""Streamlit tab (v1.0.0): SWAT+ link — land-use lookup, Curve Number runoff, RUSLE erosion and streamflow evaluation."""
import altair as alt
import pandas as pd
import streamlit as st

import swatlink as W
import ui

CODES = list(W.SWAT_TABLE)


def _class_table(ctx, layers, key):
    """Editable class -> name -> SWAT code table shared by all sections."""
    import numpy as np
    classes = sorted({int(v) for n in layers for v in np.unique(ctx.store.get(n).data[~ctx.store.get(n).mask])})
    if len(classes) > 60:
        st.error("More than 60 values: choose categorical LULC maps.")
        return None, None
    prev = st.session_state.get(f"{key}_tbl")
    names = {} if prev is None else {int(c): n for c, n in zip(prev["class"], prev["name"]) if isinstance(n, str)}
    codes = {} if prev is None else {int(c): v for c, v in zip(prev["class"], prev["SWAT code"]) if isinstance(v, str) and v}
    df = pd.DataFrame({"class": classes, "name": [names.get(c, "") for c in classes],
                       "SWAT code": [codes.get(c) or W.suggest_code(names.get(c, "")) for c in classes]})
    ed = st.data_editor(df, hide_index=True, key=f"{key}_ed", disabled=["class"],
                        column_config={"SWAT code": st.column_config.SelectboxColumn(options=CODES)})
    st.session_state[f"{key}_tbl"] = ed
    labels = {str(int(c)): n for c, n in zip(ed["class"], ed["name"]) if isinstance(n, str) and n.strip()}
    swat = {str(int(c)): s for c, s in zip(ed["class"], ed["SWAT code"]) if isinstance(s, str) and s}
    if len(swat) < len(ed):
        st.caption("⚠️ Give a class name or pick a SWAT+ code for every class (empty codes are not mapped).")
    return labels, swat


def _is_categorical(r):
    import numpy as np
    if r.data.dtype.kind not in "iu":
        return False
    sample = r.data[::7, ::7][~r.mask[::7, ::7]]
    return np.unique(sample).size <= 60


def _num_or_layer(label, R, default, key, fmt="%.4f"):
    c = st.columns([2, 1])
    v = c[0].number_input(label, value=float(default), format=fmt, key=f"{key}_n")
    lay = c[1].selectbox("or raster", ["(constant)"] + R, key=f"{key}_l")
    return v if lay == "(constant)" else lay


def render(ctx, R):
    maps = [r for r in R if "#" not in r]
    T = list(ctx.tables)
    ui.section("🏷️", "LULC → SWAT+ land-use codes", "Lookup table for QSWAT+ and area per SWAT+ code for every map / scenario", "blue")
    if not maps:
        st.info("Upload LULC maps (observed, classified or simulated scenarios) in the sidebar.")
    else:
        cat = [m for m in maps if _is_categorical(ctx.store.get(m)) and "obs_count" not in m]
        layers = st.multiselect("LULC maps (first = baseline)", maps, default=cat[: min(2, len(cat))], key="sw_layers")
        if layers:
            st.caption("Type class names to get suggested SWAT+ codes, then adjust the codes. The table is used by every section below.")
            labels, swat = _class_table(ctx, layers, "sw")
            if labels is not None and st.button("🏷️ Build lookup"):
                st.session_state.sw_lk = ctx.call("swat_landuse_lookup", {"layers": layers, "labels": labels, "swat_codes": swat})
            lk = st.session_state.get("sw_lk")
            if lk and "error" in lk:
                st.error(lk["error"])
            elif lk:
                a = pd.DataFrame(lk["area_by_class"])
                st.dataframe(a.pivot_table(index=["swat_code"], columns="layer", values="area_ha", aggfunc="sum").round(1), use_container_width=True)
                st.download_button("⬇️ QSWAT+ landuse lookup (CSV)", lk["lookup_csv"], "landuse_lookup.csv", "text/csv", key="dl_lk")

            ui.section("💧", "Curve Number runoff by scenario", "SCS-CN with hydrologic soil groups and SWAT slope adjustment", "green")
            c = st.columns(4)
            hsg_l = c[0].selectbox("Hydrologic soil group raster (1=A … 4=D)", ["(uniform)"] + maps, key="sw_hsg")
            hsg_u = c[1].selectbox("Uniform HSG", list("ABCD"), index=1, key="sw_hsgu", disabled=hsg_l != "(uniform)")
            dem = c[2].selectbox("DEM (slope-adjust CN, LS)", ["(none)"] + maps, key="sw_dem")
            lam = c[3].selectbox("Initial abstraction Ia/S", [0.2, 0.05], key="sw_lam")
            c = st.columns(4)
            storm = c[0].number_input("Design storm (mm)", 1.0, 1000.0, 50.0, key="sw_storm")
            rt = c[1].selectbox("Daily rainfall table (optional)", ["(none)"] + T, key="sw_rt")
            dc = rc = None
            if rt != "(none)":
                cols = list(ctx.tables[rt].columns)
                dc = c[2].selectbox("Date column", cols, key="sw_rdc")
                rc = c[3].selectbox("Rainfall (mm) column", cols, index=min(1, len(cols) - 1), key="sw_rrc")
            with st.expander("Edit Curve Numbers (TR-55 defaults, AMC II)"):
                cn_df = pd.DataFrame([(k, *v[:5]) for k, v in W.SWAT_TABLE.items()], columns=["code", "description", "A", "B", "C", "D"])
                cn_ed = st.data_editor(cn_df, hide_index=True, disabled=["code", "description"], key="sw_cn_ed")
            if labels is not None and st.button("💧 Compute runoff"):
                ov = {r["code"]: [r["A"], r["B"], r["C"], r["D"]] for r in cn_ed.to_dict(orient="records")}
                st.session_state.sw_cn = ctx.call("curve_number_runoff", {
                    "layers": layers, "labels": labels, "swat_codes": swat, "hsg_layer": None if hsg_l == "(uniform)" else hsg_l, "hsg_uniform": hsg_u,
                    "dem": None if dem == "(none)" else dem, "storm_mm": storm, "rain_table": None if rt == "(none)" else rt, "date_column": dc,
                    "rain_column": rc, "lam": float(lam), "cn_overrides": ov})
            res = st.session_state.get("sw_cn")
            if res and "error" in res:
                st.error(res["error"])
            elif res:
                df = pd.DataFrame(res["results"])
                st.dataframe(df, hide_index=True)
                ycol = "mean_annual_runoff_mm" if "mean_annual_runoff_mm" in df else "storm_runoff_mm"
                st.altair_chart(alt.Chart(df).mark_bar(color="#06B6D4").encode(x=alt.X(f"{ycol}:Q", title=ycol.replace("_", " ")),
                                                                                y=alt.Y("layer:N", title=None), tooltip=list(df.columns)), use_container_width=True)
                cols = st.columns(min(2, len(res["outputs"]) // 2 or 1))
                for i, n in enumerate([o for o in res["outputs"] if o.endswith("_CN.tif")][:2]):
                    with cols[i % len(cols)]:
                        st.markdown(f"**{n}**")
                        _show_cont(ctx.store.outputs[n], label="Curve Number")
                for n in res["outputs"]:
                    st.download_button(f"⬇️ {n}", ctx.store.outputs[n], n, "image/tiff", key=f"dl_cn_{n}")
                st.caption(res["note"])

            ui.section("⛰️", "RUSLE soil erosion by scenario", "A = R · K · LS · C · P with C from the SWAT+ code", "orange")
            if dem == "(none)":
                st.info("Choose a DEM above to compute LS and soil loss.")
            else:
                c = st.columns(3)
                with c[0]:
                    R_ = _num_or_layer("R (MJ mm ha⁻¹ h⁻¹ yr⁻¹)", maps, 500.0, "sw_R", "%.1f")
                with c[1]:
                    K_ = _num_or_layer("K (t ha h ha⁻¹ MJ⁻¹ mm⁻¹)", maps, 0.03, "sw_K")
                with c[2]:
                    P_ = _num_or_layer("P (support practice)", maps, 1.0, "sw_P", "%.2f")
                c = st.columns(3)
                lsm = c[0].selectbox("LS method", ["slope_length", "flow_accumulation"], key="sw_lsm",
                                     format_func=lambda x: "Fixed slope length (Wischmeier & Smith)" if x == "slope_length" else "D8 flow accumulation (Moore & Burch)")
                sl = c[1].number_input("Slope length (m)", 5.0, 1000.0, 50.0, key="sw_sl")
                ml = c[2].number_input("Max flow length (m)", 30.0, 3000.0, 300.0, key="sw_ml")
                with st.expander("Edit C factors"):
                    c_df = pd.DataFrame([(k, v[0], v[5]) for k, v in W.SWAT_TABLE.items()], columns=["code", "description", "C"])
                    c_ed = st.data_editor(c_df, hide_index=True, disabled=["code", "description"], key="sw_c_ed")
                if labels is not None and st.button("⛰️ Compute soil loss"):
                    st.session_state.sw_ru = ctx.call("rusle_erosion", {
                        "layers": layers, "dem": dem, "R": R_, "K": K_, "P": P_, "labels": labels, "swat_codes": swat, "ls_method": lsm,
                        "slope_length": sl, "max_length": ml, "c_overrides": dict(zip(c_ed["code"], c_ed["C"]))})
                res = st.session_state.get("sw_ru")
                if res and "error" in res:
                    st.error(res["error"])
                elif res:
                    df = pd.DataFrame(res["results"])
                    st.dataframe(df, hide_index=True)
                    sev = df.melt(id_vars="layer", value_vars=[c for c in df if c.endswith("_pct_area")], var_name="class", value_name="pct")
                    sev["class"] = sev["class"].str.replace("_pct_area", "")
                    st.altair_chart(alt.Chart(sev).mark_bar().encode(
                        y=alt.Y("layer:N", title=None), x=alt.X("pct:Q", stack="normalize", title="share of area"),
                        color=alt.Color("class:N", sort=["low", "moderate", "high", "very high", "severe"],
                                        scale=alt.Scale(domain=["low", "moderate", "high", "very high", "severe"],
                                                        range=["#A7F3D0", "#FDE68A", "#FDBA74", "#F87171", "#991B1B"]))), use_container_width=True)
                    with st.expander("Soil loss by land use"):
                        st.dataframe(pd.DataFrame(res["by_class"]), hide_index=True)
                    first = next((o for o in res["outputs"] if o.endswith("_soil_loss.tif")), None)
                    if first:
                        _show_cont(ctx.store.outputs[first], cap=40, cmap="YlOrRd", label="t/ha/yr (capped at 40)")
                    for n in res["outputs"]:
                        st.download_button(f"⬇️ {n}", ctx.store.outputs[n], n, "image/tiff", key=f"dl_ru_{n}")
                    st.caption(f"Severity classes (t/ha/yr): {res['severity_classes_t_ha_yr']}. {res['note']}")

    ui.section("📈", "SWAT+ streamflow evaluation", "Flow-duration curves, FDC signatures, Moriasi ratings, calibration / validation split", "violet")
    if len(T) < 1:
        st.info("Upload observed and simulated discharge CSVs (SWAT+ channel_sd output or a gauge record).")
        return
    c = st.columns(3)
    ot = c[0].selectbox("Observed table", T, key="fe_ot")
    stb = c[1].selectbox("Simulated table", T, index=min(1, len(T) - 1), key="fe_st")
    step = c[2].selectbox("Time step", ["daily", "monthly", "annual"], key="fe_step")
    oc_, sc_ = list(ctx.tables[ot].columns), list(ctx.tables[stb].columns)
    c = st.columns(5)
    dcol = c[0].selectbox("Date column", oc_, key="fe_dc")
    ocol = c[1].selectbox("Observed column", oc_, index=min(1, len(oc_) - 1), key="fe_oc")
    scol = c[2].selectbox("Simulated column", sc_, index=min(2 if stb == ot else 1, len(sc_) - 1), key="fe_sc")
    warm = c[3].text_input("Warm-up ends (YYYY-MM-DD)", key="fe_warm")
    split = c[4].text_input("Validation starts (YYYY-MM-DD)", key="fe_split")
    if st.button("📈 Evaluate"):
        st.session_state.fe = ctx.call("flow_evaluation", {"observed_table": ot, "simulated_table": stb, "date_column": dcol, "observed_column": ocol,
                                                           "simulated_column": scol, "split_date": split or None, "step": step, "warmup_end": warm or None})
    res = st.session_state.get("fe")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        periods = [p for p in ("calibration", "validation", "all") if p in res]
        rows = []
        for p in periods:
            sc = res[p]
            rows.append(dict(period=p, n=sc["n"], NSE=sc["nse"], KGE=sc["kge"], R2=sc["r2"], PBIAS=sc["pbias_percent"], RSR=sc["rsr"],
                             FHV=sc["pbias_fhv"], FLV=sc["pbias_flv"], FMS=sc["pbias_fms"],
                             rating_NSE=sc["ratings"]["nse"], rating_PBIAS=sc["ratings"]["pbias_percent"], rating_R2=sc["ratings"]["r2"], rating_RSR=sc["ratings"]["rsr"]))
        st.dataframe(pd.DataFrame(rows).round(3), hide_index=True)
        f = pd.DataFrame(res["fdc"])
        fl = f.melt(id_vars="exceedance", var_name="series", value_name="flow")
        st.altair_chart(alt.Chart(fl).mark_line().encode(x=alt.X("exceedance:Q", title="exceedance probability"),
                                                         y=alt.Y("flow:Q", scale=alt.Scale(type="symlog"), title="flow"),
                                                         color=alt.Color("series:N", scale=alt.Scale(range=["#06B6D4", "#EC4899"]))).properties(title="Flow-duration curve"),
                        use_container_width=True)
        st.caption(f"{res['period']} · {res['note']}")

    ui.section("🔀", "LULC impact between two SWAT+ runs", "Same climate and parameters, different land-use map", "pink")
    c = st.columns(5)
    bt = c[0].selectbox("Baseline run table", T, key="at_bt")
    stt = c[1].selectbox("Scenario run table", T, index=min(1, len(T) - 1), key="at_st")
    adc = c[2].selectbox("Date column", list(ctx.tables[bt].columns), key="at_dc")
    bc = c[3].selectbox("Baseline flow column", list(ctx.tables[bt].columns), index=min(1, len(ctx.tables[bt].columns) - 1), key="at_bc")
    scc = c[4].selectbox("Scenario flow column", list(ctx.tables[stt].columns), index=min(1, len(ctx.tables[stt].columns) - 1), key="at_sc")
    if st.button("🔀 Compare runs"):
        st.session_state.at = ctx.call("lulc_flow_attribution", {"baseline_table": bt, "scenario_table": stt, "date_column": adc,
                                                                 "baseline_column": bc, "scenario_column": scc})
    res = st.session_state.get("at")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        m = st.columns(4)
        m[0].metric("Mean flow", f"{res['mean_change_pct']:+.1f}%")
        m[1].metric("High flow Q5", f"{res['Q5_change_pct']:+.1f}%")
        m[2].metric("Median Q50", f"{res['Q50_change_pct']:+.1f}%")
        m[3].metric("Low flow Q95", f"{res['Q95_change_pct']:+.1f}%")
        f = pd.DataFrame(res["fdc"]).melt(id_vars="exceedance", var_name="run", value_name="flow")
        st.altair_chart(alt.Chart(f).mark_line().encode(x="exceedance:Q", y=alt.Y("flow:Q", scale=alt.Scale(type="symlog")),
                                                        color=alt.Color("run:N", scale=alt.Scale(range=["#8B5CF6", "#F97316"]))), use_container_width=True)
        st.caption(res["note"])


def _show_cont(raw, cap=None, cmap="viridis", label=None):
    import matplotlib.pyplot as plt
    import numpy as np
    from rasterio.io import MemoryFile
    with MemoryFile(raw) as mf, mf.open() as src:
        a = src.read(1).astype(float)
        nd = src.nodata
    if nd is not None:
        a[a == nd] = np.nan
    fig, ax = plt.subplots(figsize=(6, 4), dpi=110)
    im = ax.imshow(a, cmap=cmap, vmax=cap, interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.8, label=label or "")
    ax.set_axis_off()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

