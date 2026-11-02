"""Streamlit tab (v0.9.0): drivers, Markov-CA scenario simulation and hindcast validation."""
import re

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import simulate as S
import ui
from changeops import _year_guess
from classify_tab import _show


def _parse_pairs(txt):
    return [m.group(1) + "->" + m.group(2) for m in re.finditer(r"(\d+)\s*-+>\s*(\d+)", txt or "")]


def _parse_mult(txt):
    return {f"{a}->{b}": float(f) for a, b, f in re.findall(r"(\d+)\s*-+>\s*(\d+)\s*[:=]\s*([0-9.]+)", txt or "")}


def _codes(ctx, names):
    vals = set()
    for n in names:
        r = ctx.store.get(n)
        v = np.unique(r.data[~r.mask])
        if v.size <= 60:
            vals |= {int(x) for x in v}
    return sorted(vals)


def _driver_ui(ctx, R, codes, key):
    c = st.columns(4)
    dc = c[0].multiselect("Distance to classes (dynamic)", codes, default=codes[:2], key=f"{key}_dc")
    dl = c[1].multiselect("Distance to features (roads, rivers, towns)", R, key=f"{key}_dl")
    dem = c[2].selectbox("Slope from DEM", ["(none)"] + R, key=f"{key}_dem")
    lay = c[3].multiselect("Continuous layers (DEM, population)", R, key=f"{key}_lay")
    d = [dict(type="distance_to_class", **{"class": int(x)}) for x in dc]
    d += [dict(type="distance_to_layer", name=x) for x in dl]
    d += [dict(type="slope", name=dem)] if dem != "(none)" else []
    d += [dict(type="layer", name=x) for x in lay]
    return d, dc, dl, None if dem == "(none)" else dem


def render(ctx, R):
    ui.section("🧭", "Drivers of change", "Distance and terrain drivers, Cramér's V, AUC and multicollinearity per transition", "blue")
    maps = [r for r in R if "#" not in r]
    if len(maps) < 2:
        st.info("Upload at least two LULC maps on one grid (three for a hindcast), plus optional roads / rivers rasters, DEM and protected-area mask.")
        return
    c = st.columns(4)
    m0 = c[0].selectbox("Calibration: earlier map", maps, key="sm_m0")
    m1 = c[1].selectbox("Calibration: later map", maps, index=1, key="sm_m1")
    y0 = c[2].number_input("Year of earlier map", 1900, 2200, _year_guess(m0, 2000), key=f"sm_y0_{m0}")
    y1 = c[3].number_input("Year of later map", 1900, 2200, _year_guess(m1, 2010), key=f"sm_y1_{m1}")
    try:
        codes = _codes(ctx, [m0, m1])
    except Exception as e:  # noqa: BLE001
        st.error(str(e))
        return
    drivers, dc, dl, dem = _driver_ui(ctx, maps, codes, "sm")
    c = st.columns(2)
    if c[0].button("🧭 Analyse drivers"):
        st.session_state.sm_drv = ctx.call("driver_analysis", {"map_from": m0, "map_to": m1, "drivers": drivers})
    if c[1].button("💾 Export driver GeoTIFFs (also for MOLUSCE)"):
        out = ctx.call("make_driver_layers", {"base_map": m1, "classes": dc, "layers": dl, "dem": dem})
        st.session_state.sm_exp = out
    if st.session_state.get("sm_exp"):
        out = st.session_state.sm_exp
        if "error" in out:
            st.error(out["error"])
        else:
            for n in out["outputs"]:
                if n in ctx.store.outputs:
                    st.download_button(f"⬇️ {n}", ctx.store.outputs[n], n, "image/tiff", key=f"dl_drv_{n}")
    res = st.session_state.get("sm_drv")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        sc = pd.DataFrame(res["screening"])
        if len(sc):
            long = sc.melt(id_vars=["transition", "driver"], value_vars=["cramers_v", "auc"], var_name="metric")
            heat = alt.Chart(long).mark_rect().encode(
                x=alt.X("transition:N"), y=alt.Y("driver:N", title=None), color=alt.Color("value:Q", scale=alt.Scale(scheme="viridis")),
                tooltip=["transition", "driver", "metric", alt.Tooltip("value:Q", format=".3f")]).properties(height=28 * sc["driver"].nunique() + 20)
            text = alt.Chart(long).mark_text(fontSize=11, color="white").encode(x="transition:N", y="driver:N", text=alt.Text("value:Q", format=".2f"))
            st.altair_chart((heat + text).facet(column=alt.Column("metric:N", title=None)), use_container_width=False)
        c = st.columns(2)
        c[0].markdown("**Variance inflation factor**")
        c[0].dataframe(pd.DataFrame({"driver": list(res["vif"]), "VIF": list(res["vif"].values())}), hide_index=True)
        c[1].markdown("**Driver correlation**")
        c[1].dataframe(pd.DataFrame(res["correlation"]), hide_index=True)
        st.caption(res["note"])

    ui.section("🔮", "Scenario simulation", "Markov quantity + transition potentials + cellular-automaton allocation", "violet")
    mode = st.radio("Mode", ["Hindcast (validate against an observed map)", "Future scenario"], horizontal=True, key="sm_mode")
    if mode.startswith("Hindcast"):
        c = st.columns(3)
        obs = c[0].selectbox("Observed map to reproduce", [m for m in maps if m not in (m0, m1)] or maps, key="sm_obs")
        ty = c[1].number_input("Its year", 1900, 2200, _year_guess(obs, int(y1) + 10), key=f"sm_ty_{obs}")
        others = c[2].multiselect("Other simulated maps to compare (e.g. MOLUSCE output)", [m for m in maps if m not in (m0, m1, obs)], key="sm_others")
        start, start_year = m1, int(y1)
        st.caption(f"Calibrates on {m0} → {m1}, simulates {ty} from {m1}, compares with {obs}.")
    else:
        c = st.columns(2)
        ty = c[0].number_input("Target year", 1900, 2300, int(y1) + (int(y1) - int(y0)), key="sm_target")
        start = c[1].selectbox("Start map (usually the latest)", maps, index=maps.index(m1), key="sm_start")
        start_year = int(y1) if start == m1 else _year_guess(start, int(y1))
        obs, others = None, []
    c = st.columns(5)
    model = c[0].selectbox("Potential model", S.POTENTIAL_MODELS, key="sm_model")
    ntr = c[1].number_input("Transitions to model", 1, 20, 6, key="sm_ntr")
    nb = c[2].selectbox("Neighbourhood", [3, 5, 7], key="sm_nb")
    w = c[3].slider("Neighbourhood weight", 0.0, 1.0, 0.5, 0.05, key="sm_w")
    its = c[4].number_input("CA iterations", 1, 50, 10, key="sm_its")
    c = st.columns(4)
    scen = c[0].selectbox("Scenario", list(S.SCENARIOS), key="sm_scen")
    growth = c[1].multiselect("Development class(es) (e.g. built-up)", codes, key="sm_growth")
    natural = c[2].multiselect("Natural class(es) (forest, wetland)", codes, key="sm_nat")
    prot = c[3].selectbox("Protected-area mask (non-zero = no change)", ["(none)"] + maps, key="sm_prot")
    c = st.columns(3)
    forb = c[0].text_input("Forbidden transitions", "", placeholder="e.g. 1->3, 3->2", key="sm_forb")
    mult = c[1].text_input("Demand multipliers", "", placeholder="e.g. 4->3:1.3", key="sm_mult")
    stoch = c[2].slider("Stochastic perturbation", 0.0, 1.0, 0.0, 0.05, key="sm_sto")
    potm = st.checkbox("Also save transition-potential maps", key="sm_pot")
    out = st.text_input("Output name", f"sim_{scen.split()[0].lower()}_{ty}.tif", key=f"sm_out_{scen}_{ty}")
    st.caption("Scenario presets scale demand: development class gain ×0.6 (ecological protection) or ×1.5 (development priority); loss of "
               "natural classes ×0.5 / ×1.2; ecological protection applies the protected-area mask.")
    args = {"map_from": m0, "map_to": m1, "year_from": int(y0), "year_to": int(y1), "year_target": int(ty), "start_map": start,
            "start_year": start_year, "drivers": drivers, "model": model, "n_transitions": int(ntr), "scenario": scen, "growth_classes": growth,
            "natural_classes": natural, "multipliers": _parse_mult(mult), "forbidden": _parse_pairs(forb),
            "protected_layer": None if prot == "(none)" else prot, "neighbourhood": int(nb), "weight": float(w), "iterations": int(its),
            "stochastic": float(stoch), "output_name": out, "potential_prefix": out.rsplit(".", 1)[0] + "_potential" if potm else None,
            "validate_against": obs, "compare_with": others}
    c = st.columns(2)
    if c[0].button("🔮 Run simulation", type="primary"):
        with st.spinner("Calibrating, projecting and allocating…"):
            st.session_state.sm_res = ctx.call("simulate_lulc", args)
        st.rerun()
    if mode == "Future scenario" and c[1].button("⚖️ Run and compare all three scenarios"):
        rows = []
        with st.spinner("Running BAU, ecological protection and development priority…"):
            for sname in S.SCENARIOS:
                a = dict(args, scenario=sname, output_name=f"sim_{sname.split()[0].lower()}_{ty}.tif", potential_prefix=None)
                r = ctx.call("simulate_lulc", a)
                if "error" in r:
                    st.error(r["error"])
                    break
                rows += [dict(scenario=sname, **x) for x in r["simulation"]["area_table"]]
        st.session_state.sm_cmp = rows
        st.rerun()

    if st.session_state.get("sm_cmp"):
        df = pd.DataFrame(st.session_state.sm_cmp)
        df["class"] = df["class"].astype(str)
        st.markdown("**Scenario comparison: simulated area (ha)**")
        st.altair_chart(alt.Chart(df).mark_bar().encode(x=alt.X("class:N"), xOffset="scenario:N", y=alt.Y("simulated_ha:Q", title="ha"),
                                                         color=alt.Color("scenario:N", scale=alt.Scale(range=["#8B5CF6", "#10B981", "#F97316"])),
                                                         tooltip=["scenario", "class", "start_ha", "simulated_ha", "change_ha"]), use_container_width=True)
        st.dataframe(df.pivot(index="class", columns="scenario", values="change_ha").round(1).add_prefix("Δ ha · "))

    res = st.session_state.get("sm_res")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        sim = res["simulation"]
        m = st.columns(4)
        m[0].metric("Target year", sim["target_year"])
        m[1].metric("Calibration change modelled", f"{100 * (sim['share_of_calibration_change_modelled'] or 0):.0f}%")
        m[2].metric("Protected pixels", f"{sim['protected_pixels']:,}")
        m[3].metric("Unmet demand (px)", f"{sum(sim['unmet_demand_pixels'].values()):,}")
        c = st.columns(2)
        with c[0]:
            st.markdown("**Transitions, potential-model AUC and demand**")
            tm = pd.DataFrame(sim["transitions_modelled"])
            tm["demand_px"] = tm["transition"].map(sim["demand_pixels"])
            st.dataframe(tm, hide_index=True)
            st.markdown("**Area change**")
            st.dataframe(pd.DataFrame(sim["area_table"]), hide_index=True)
        with c[1]:
            if sim["output"] in ctx.store.outputs:
                _show(ctx.store.outputs[sim["output"]])
                st.download_button(f"⬇️ Download {sim['output']}", ctx.store.outputs[sim["output"]], sim["output"], "image/tiff", key="dl_sim")
        with st.expander("Markov transition matrix used for the projection"):
            mk = sim["markov_matrix"]
            st.dataframe(pd.DataFrame(mk["P"], index=[f"from {c}" for c in mk["classes"]], columns=[f"to {c}" for c in mk["classes"]]))
            st.caption(f"Projected over {mk['years']} years from the calibration interval.")
        for n in sim.get("potential_maps", []):
            st.download_button(f"⬇️ {n}", ctx.store.outputs[n], n, "image/tiff", key=f"dl_pot_{n}")
        if res.get("validation"):
            v = res["validation"]
            st.markdown(f"**Hindcast validation against {v['observed']}** ({v['compared_pixels']:,} pixels)")
            vt = pd.DataFrame(v["results"])
            st.dataframe(vt[["model", "fom", "kappa_simulation", "hits", "misses", "wrong_hits", "false_alarms", "producers_change", "users_change",
                             "quantity_disagreement", "allocation_disagreement", "overall_agreement"]], hide_index=True)
            long = vt.melt(id_vars="model", value_vars=["hits", "misses", "wrong_hits", "false_alarms"], var_name="component")
            st.altair_chart(alt.Chart(long).mark_bar().encode(
                y=alt.Y("model:N", title=None), x=alt.X("value:Q", stack="normalize", title="share of change pixels"),
                color=alt.Color("component:N", scale=alt.Scale(domain=["hits", "wrong_hits", "misses", "false_alarms"],
                                                               range=["#10B981", "#F59E0B", "#EF4444", "#8B5CF6"]))), use_container_width=True)
            st.caption(v["note"])
        st.caption(sim["note"])
