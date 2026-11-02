"""Streamlit tabs added in v0.6.0: area-adjusted accuracy and intensity analysis."""
import io
import json

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import olofsson
import ui

Z = olofsson.Z95


def _labels(key):
    txt = st.text_input('Optional class names as JSON, e.g. {"1": "Water", "2": "Built-up"}', key=key)
    try:
        return json.loads(txt) if txt.strip() else None
    except Exception:
        st.warning("Could not read the class-name JSON; showing codes only.")
        return None


def _excel(sheets: dict) -> tuple:
    bio = io.BytesIO()
    try:
        with pd.ExcelWriter(bio) as xw:
            for name, df in sheets.items():
                df.to_excel(xw, sheet_name=name[:31], index=False)
        return bio.getvalue(), "xlsx"
    except ImportError:  # openpyxl missing: fall back to one CSV
        out = io.StringIO()
        for name, df in sheets.items():
            out.write(f"# {name}\n")
            df.to_csv(out, index=False)
            out.write("\n")
        return out.getvalue().encode(), "csv"


def _download(sheets, stem, key):
    data, ext = _excel(sheets)
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if ext == "xlsx" else "text/csv"
    st.download_button(f"⬇️ Download all tables (.{ext})", data, f"{stem}.{ext}", mime, key=key)


# ====================================================================== accuracy
def _show_accuracy(res):
    u = res["area_unit"]
    p = res["pontius"]
    m = st.columns(4)
    m[0].metric("Overall accuracy", f"{100 * res['overall_accuracy']:.1f}%", f"± {100 * res['overall_accuracy_ci95']:.1f}% (95% CI)", delta_color="off")
    m[1].metric("Quantity disagreement", f"{100 * p['quantity']:.1f}%")
    m[2].metric("Allocation disagreement", f"{100 * p['allocation']:.1f}%", f"exchange {100 * p['exchange']:.1f}% · shift {100 * p['shift']:.1f}%", delta_color="off")
    m[3].metric("Kappa (legacy)", f"{res['kappa_sample_counts']:.3f}")
    for w in res.get("warnings", []):
        st.warning(w)
    ct = pd.DataFrame(res["classes"])
    st.dataframe(ct, hide_index=True)
    ma, aa, ci = f"mapped area ({u})", f"adjusted area ({u})", f"± 95% CI ({u})"
    plot = pd.DataFrame({"class": ct["class"].astype(str), "mapped": ct[ma], "adjusted": ct[aa],
                         "lo": ct[aa] - ct[ci], "hi": ct[aa] + ct[ci]})
    base = alt.Chart(plot).encode(y=alt.Y("class:N", title=None))
    chart = (base.mark_bar(opacity=0.35, color="#8B5CF6").encode(x=alt.X("mapped:Q", title=f"Area ({u})"), tooltip=["class", "mapped"])
             + base.mark_rule(strokeWidth=2, color="#EC4899").encode(x="lo:Q", x2="hi:Q")
             + base.mark_point(filled=True, size=80, color="#EC4899").encode(x="adjusted:Q", tooltip=["class", "adjusted", "lo", "hi"]))
    st.altair_chart(chart, use_container_width=True)
    st.caption("Bars: mapped (pixel-count) area. Dots and whiskers: error-adjusted area ± 95% CI. A bar outside its whisker means the pixel count is biased.")
    c = st.columns(2)
    sm, pm = pd.DataFrame(res["sample_matrix"]), pd.DataFrame(res["proportion_matrix"])
    c[0].markdown("**Sample counts** (rows map, columns reference)")
    c[0].dataframe(sm, hide_index=True)
    c[1].markdown("**Area-proportion matrix**")
    c[1].dataframe(pm, hide_index=True)
    with st.expander("Pontius components per class"):
        st.dataframe(pd.DataFrame(res["pontius_per_class"]), hide_index=True)
    st.text_area("📝 Methods & results text (copy into your thesis)", res["methods_text"], height=200)
    _download({"classes": ct, "sample_counts": sm, "area_proportions": pm, "pontius": pd.DataFrame(res["pontius_per_class"]),
               "methods": pd.DataFrame({"text": [res["methods_text"]]})}, "area_adjusted_accuracy", "dl_aaa")


def render_accuracy(ctx, R, T):
    ui.section("📏", "Area-adjusted accuracy", "Olofsson et al. (2014) good practice: error-adjusted areas and accuracies with 95% confidence intervals", "orange")
    mode = st.radio("Workflow", ["Assess map with validation points", "Design sample & generate points", "From a published error matrix"], horizontal=True, key="aaa_mode")
    unit = st.selectbox("Area unit", ["ha", "km2", "m2"], key="aaa_unit")

    if mode == "Design sample & generate points":
        if not R:
            st.info("Upload a classified raster in the sidebar.")
            return
        a = st.selectbox("Classified raster", R, key="aaa_dr")
        c = st.columns(4)
        ua = c[0].number_input("Expected user's accuracy", 0.5, 0.99, 0.85, 0.01)
        se = c[1].number_input("Target SE of overall accuracy", 0.002, 0.05, 0.01, 0.001, format="%.3f")
        alloc = c[2].selectbox("Allocation", ["olofsson", "proportional", "equal", "neyman"])
        mn = c[3].number_input("Min. per class", 0, 1000, 50, 5)
        res = ctx.call("design_accuracy_sample", {"raster": a, "expected_users_accuracy": ua, "target_se": se, "allocation": alloc, "min_per_class": int(mn)})
        if "error" in res:
            st.error(res["error"])
            return
        d = pd.DataFrame(res["design"])
        st.dataframe(d, hide_index=True)
        st.caption(f"Formula total n = {res['n_total_formula']}; allocated = {res['n_allocated']}. {res['note']}")
        seed = st.number_input("Random seed", 0, 10**6, 42)
        if st.button("🎲 Generate stratified random points"):
            out = ctx.call("generate_sample_points", {"raster": a, "n_per_class": {str(k): int(v) for k, v in zip(d["class"], d["n_samples"])},
                                                      "seed": int(seed), "table_name": "accuracy_points.csv"})
            if "error" in out:
                st.error(out["error"])
            else:
                st.success(f"{out['points']} points saved as table `accuracy_points.csv` (order shuffled so the interpreter is blind to the map).")
        if "accuracy_points.csv" in ctx.tables:
            pts = ctx.tables["accuracy_points.csv"]
            st.download_button("⬇️ Blind sheet for interpreters (CSV)", pts.drop(columns=["map_class"]).to_csv(index=False), "accuracy_points_blind.csv", key="dl_blind")
            st.download_button("⬇️ Full sheet with map class (CSV)", pts.to_csv(index=False), "accuracy_points_full.csv", key="dl_full")
        return

    if mode == "From a published error matrix":
        k = int(st.number_input("Number of classes", 2, 30, 4))
        names = [c.strip() for c in st.text_input("Class names (comma-separated)", ", ".join(f"class {i + 1}" for i in range(k))).split(",")]
        names = (names + [f"class {i + 1}" for i in range(len(names), k)])[:k]
        st.markdown("Sample counts: rows = **map**, columns = **reference**")
        n = st.data_editor(pd.DataFrame(np.zeros((k, k), int), index=names, columns=names), key=f"aaa_n{k}")
        a = st.data_editor(pd.DataFrame({f"mapped area ({unit})": np.zeros(k)}, index=names), key=f"aaa_a{k}")
        if st.button("📏 Compute"):
            if n.to_numpy().sum() == 0 or a.iloc[:, 0].sum() == 0:
                st.error("Enter sample counts and mapped areas first.")
                return
            r = olofsson.olofsson_accuracy(n.to_numpy(), a.iloc[:, 0].to_numpy(), names, unit)
            res = r.summary()
            res.update(sample_matrix=r.sample_matrix_df().reset_index().to_dict(orient="list"),
                       proportion_matrix=r.proportion_matrix_df().round(6).reset_index().to_dict(orient="list"),
                       pontius_per_class=r.pontius["per_class"].round(6).to_dict(orient="records"), methods_text=r.methods_text())
            ctx.record("area_adjusted_accuracy (manual matrix)", {"classes": names, "unit": unit}, f"OA={r.overall:.4f}")
            _show_accuracy(res)
        return

    if not R or not T:
        st.info("Upload a classified raster and a validation CSV (x, y, reference class) in the sidebar. No points yet? Use *Design sample & generate points*.")
        return
    a = st.selectbox("Classified raster", R, key="aaa_r")
    tb = st.selectbox("Validation table", T, key="aaa_t")
    cols = list(ctx.tables[tb].columns)
    guess = lambda keys, d=0: next((cols.index(c) for c in cols if c.lower() in keys), min(d, len(cols) - 1))  # noqa: E731
    c = st.columns(4)
    rc = c[0].selectbox("Reference column", cols, index=guess({"reference", "reference_class", "ref", "class", "truth"}), key="aaa_rc")
    xc = c[1].selectbox("X column", cols, index=guess({"x", "lon", "longitude", "easting"}), key="aaa_xc")
    yc = c[2].selectbox("Y column", cols, index=guess({"y", "lat", "latitude", "northing"}, 1), key="aaa_yc")
    epsg = c[3].number_input("Point EPSG (0 = same as raster)", 0, 99999, 4326 if xc.lower() in ("lon", "longitude") else 0, key="aaa_epsg")
    labels = _labels("aaa_lab")
    if st.button("📏 Run area-adjusted assessment"):
        res = ctx.call("area_adjusted_accuracy", {"raster": a, "table": tb, "reference_column": rc, "x_column": xc, "y_column": yc,
                                                  "epsg": int(epsg) or None, "unit": unit, "labels": labels})
        if "error" in res:
            st.error(res["error"])
        else:
            st.caption(f"{res['points_used']} points used, {res['points_skipped']} skipped. {res['note']}")
            _show_accuracy(res)


# ====================================================================== intensity
def _bars(df, cat, val, ref, ref_title, colour, title):
    base = alt.Chart(df)
    bars = base.mark_bar(color=colour).encode(y=alt.Y(f"{cat}:N", title=None, sort=None), x=alt.X(f"{val}:Q", title="% per year"),
                                              tooltip=list(df.columns))
    rule = base.mark_rule(color="#111827", strokeDash=[5, 3], strokeWidth=2).encode(x=f"{ref}:Q", tooltip=[alt.Tooltip(f"{ref}:Q", title=ref_title)])
    return (bars + rule).properties(title=title, height=max(120, 26 * df[cat].nunique()))


def render_intensity(ctx, R):
    ui.section("📈", "Intensity analysis", "Aldwaik & Pontius (2012): interval, category and transition levels across multiple dates", "violet")
    if len(R) < 2:
        st.info("Upload at least two LULC rasters on the same grid (e.g. 2000, 2010, 2020) in the sidebar.")
        return
    layers = st.multiselect("LULC rasters (any order; sorted by year)", R, default=R[: min(3, len(R))], key="ia_layers")
    if len(layers) < 2:
        st.info("Select two or more rasters.")
        return
    from changeops import _year_guess
    yc = st.columns(len(layers))
    years = [yc[i].number_input(f"Year of {n}", 1900, 2200, _year_guess(n, 2000 + 10 * i), key=f"ia_y_{n}") for i, n in enumerate(layers)]
    unit = st.selectbox("Area unit", ["ha", "km2", "m2"], key="ia_unit")
    labels = _labels("ia_lab")
    if st.button("📈 Run intensity analysis"):
        st.session_state.ia_res = ctx.call("intensity_analysis", {"layers": layers, "years": years, "unit": unit, "labels": labels})
    res = st.session_state.get("ia_res")
    if not res:
        return
    if "error" in res:
        st.error(res["error"])
        return
    u = res["area_unit"]
    iv, cat = pd.DataFrame(res["interval"]), pd.DataFrame(res["category"])
    tg, tl = pd.DataFrame(res["transition_gain"]), pd.DataFrame(res["transition_loss"])

    st.markdown("#### 1 · Interval level")
    m = st.columns(len(iv) + 1)
    m[0].metric("Uniform intensity U", f"{res['uniform_intensity_pct_per_year']:.2f} %/yr")
    for col, r in zip(m[1:], iv.to_dict(orient="records")):
        col.metric(r["interval"], f"{r['S_annual_pct']:.2f} %/yr", r["speed"], delta_color="normal" if r["speed"] == "fast" else "inverse")
    st.altair_chart(_bars(iv, "interval", "S_annual_pct", "U_uniform_pct", "uniform U", "#8B5CF6", "Annual change intensity vs uniform (dashed)"), use_container_width=True)

    st.markdown("#### 2 · Category level")
    it = st.selectbox("Interval", iv["interval"].tolist(), key="ia_it")
    sub = cat[cat["interval"] == it]
    c = st.columns(2)
    c[0].altair_chart(_bars(sub, "category", "G_gain_intensity", "S_annual_pct", "interval intensity", "#10B981", "Gross gain intensity (active if > dashed)"), use_container_width=True)
    c[1].altair_chart(_bars(sub, "category", "L_loss_intensity", "S_annual_pct", "interval intensity", "#F97316", "Gross loss intensity (active if > dashed)"), use_container_width=True)
    st.dataframe(sub.drop(columns=["interval"]), hide_index=True)

    st.markdown("#### 3 · Transition level")
    c = st.columns(2)
    g = c[0].selectbox("Gain of category", res["classes"], key="ia_g")
    sg = tg[(tg["interval"] == it) & (tg["to"] == g)]
    c[0].altair_chart(_bars(sg, "from", "R_intensity", "W_uniform", "uniform W", "#06B6D4", f"Gain of {g}: from which categories? (targeted if > dashed)"), use_container_width=True)
    lsel = c[1].selectbox("Loss of category", res["classes"], key="ia_l")
    sl = tl[(tl["interval"] == it) & (tl["from"] == lsel)]
    c[1].altair_chart(_bars(sl, "to", "Q_intensity", "V_uniform", "uniform V", "#EC4899", f"Loss of {lsel}: to which categories? (targeted if > dashed)"), use_container_width=True)

    st.markdown("#### Stationarity and change components")
    c = st.columns(2)
    c[0].dataframe(pd.DataFrame(res["stationarity_category"]), hide_index=True)
    c[1].dataframe(pd.DataFrame(res["components"]), hide_index=True)
    st.caption(f"Areas in {u}. Alternation = sum of interval changes minus first-to-last change: change that reversed (real or map error).")

    with st.expander("Transition matrices"):
        for i, mtx in enumerate(res["matrices"]):
            st.markdown(f"**{res['years'][i]} → {res['years'][i + 1]}** ({u}, rows = from, columns = to)")
            st.dataframe(pd.DataFrame(mtx, index=res["classes"], columns=res["classes"]))

    st.text_area("📝 Methods & results text", res["methods_text"], height=200, key="ia_txt")
    _download({"interval": iv, "category": cat, "transition_gain": tg, "transition_loss": tl,
               "stationarity": pd.DataFrame(res["stationarity_category"]), "components": pd.DataFrame(res["components"]),
               "methods": pd.DataFrame({"text": [res["methods_text"]]})}, "intensity_analysis", "dl_ia")

    st.markdown("#### Change maps")
    c = st.columns(3)
    sorted_layers = res["layers"]
    if c[0].button("🔁 Change-frequency raster"):
        out = ctx.call("change_frequency_raster", {"layers": sorted_layers, "output_name": "change_frequency.tif"})
        (st.error(out["error"]) if "error" in out else st.json(out["pixels_by_number_of_changes"]))
    code = c[1].selectbox("Trajectory of class code", [int(str(x).split()[0]) for x in res["classes"]], key="ia_tc")
    if c[2].button("🧭 Trajectory raster"):
        out = ctx.call("trajectory_raster", {"layers": sorted_layers, "category": int(code), "output_name": f"trajectory_class{code}.tif", "unit": u})
        if "error" in out:
            st.error(out["error"])
        else:
            st.dataframe(pd.DataFrame({"trajectory": list(out["area_by_trajectory"]), f"area ({u})": list(out["area_by_trajectory"].values())}), hide_index=True)
            st.caption(out["note"])
    for n, b in ctx.store.outputs.items():
        if n.startswith(("change_frequency", "trajectory_")):
            st.download_button(f"⬇️ Download {n}", b, file_name=n, mime="image/tiff", key=f"dl_ia_{n}")
