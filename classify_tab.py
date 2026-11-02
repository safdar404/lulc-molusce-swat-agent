"""Streamlit tab (v0.8.0): spectral indices and LULC classification."""
import json

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from rasterio.io import MemoryFile

import classify
import ui

PALETTE = ["#1F77B4", "#2CA02C", "#D62728", "#FF7F0E", "#9467BD", "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF"]


def _preview(raw, labels=None, continuous=False):
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    with MemoryFile(raw) as mf, mf.open() as src:
        a = src.read(1).astype(float)
        nd = src.nodata
    if nd is not None:
        a[a == nd] = np.nan
    fig, ax = plt.subplots(figsize=(6.2, 4.4), dpi=110)
    if continuous:
        im = ax.imshow(a, cmap="magma", vmin=0, vmax=1, interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8, label="confidence")
    else:
        vals = [int(v) for v in np.unique(a[np.isfinite(a)])]
        lut = {v: i for i, v in enumerate(vals)}
        idx = np.vectorize(lambda v: lut.get(int(v), -1) if np.isfinite(v) else -1, otypes=[float])(a) if len(vals) < 30 else a
        idx = np.where(idx < 0, np.nan, idx)
        ax.imshow(idx, cmap=ListedColormap([PALETTE[i % 10] for i in range(len(vals))]), vmin=-0.5, vmax=len(vals) - 0.5, interpolation="nearest")
        ax.legend(handles=[Patch(color=PALETTE[i % 10], label=f"{v} {(labels or {}).get(str(v), '')}") for i, v in enumerate(vals)],
                  loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7, frameon=False)
    ax.set_axis_off()
    fig.tight_layout()
    return fig


def _show(raw, **kw):
    import matplotlib.pyplot as plt
    fig = _preview(raw, **kw)
    st.pyplot(fig)
    plt.close(fig)


def _labels(key):
    txt = st.text_input('Class names as JSON, e.g. {"1": "Water", "2": "Vegetation", "3": "Built-up", "4": "Bare"}', key=key)
    try:
        return json.loads(txt) if txt.strip() else None
    except Exception:
        st.warning("Could not read the class-name JSON.")
        return None


def _cv_block(name, d):
    st.markdown(f"**{name}** · {d['folds']} folds" + (f", {d['blocks']} blocks of {d['block_m']:.0f} m" if "blocks" in d else ""))
    m = st.columns(3)
    m[0].metric("Overall accuracy", f"{100 * d['overall_accuracy']:.1f}%")
    m[1].metric("Kappa", f"{d['kappa']:.3f}")
    m[2].metric("Macro F1", f"{d['macro_f1']:.3f}")


def render(ctx, R):
    ui.section("🛰️", "Classification engine", "Spectral indices, Random Forest / boosting / SVM / maximum likelihood with spatial cross-validation", "blue")
    if not R:
        st.info("Upload a multi-band image (e.g. a Sentinel-2 or Landsat stack) or single-band files in the sidebar, plus a training CSV (x, y, class code).")
        return
    stacks = [n for n in R if "#" not in n and ctx.store.band_count(n) > 1]
    mode = st.radio("Image input", ["One multi-band file", "Separate band files"], horizontal=True, index=0 if stacks else 1, key="cl_mode")
    band_map, stack, preset = {}, None, None
    if mode == "One multi-band file":
        if not stacks:
            st.warning("No multi-band GeoTIFF loaded; choose *Separate band files* or upload a stack.")
            return
        c = st.columns(2)
        stack = c[0].selectbox("Image stack", stacks, key="cl_stack")
        preset = c[1].selectbox("Sensor preset (band order)", list(classify.PRESETS), key="cl_preset")
        n = ctx.store.band_count(stack)
        p = classify.PRESETS[preset]
        with st.expander(f"Band roles ({n} bands in file) — edit if your band order differs", expanded=not p["bands"]):
            cols = st.columns(5)
            for i, role in enumerate(classify.ROLES):
                opts = ["(none)"] + [str(b) for b in range(1, n + 1)]
                dflt = str(p["bands"].get(role, "(none)")) if p["bands"].get(role, 0) <= n else "(none)"
                v = cols[i % 5].selectbox(role, opts, index=opts.index(dflt), key=f"cl_role_{role}_{preset}")
                if v != "(none)":
                    band_map[role] = f"{stack}#{v}"
        scale0, off0 = p["scale"], p["offset"]
    else:
        cols = st.columns(5)
        for i, role in enumerate(classify.ROLES):
            v = cols[i % 5].selectbox(role, ["(none)"] + R, key=f"cl_sep_{role}")
            if v != "(none)":
                band_map[role] = v
        scale0, off0 = 1e-4, 0.0
    c = st.columns(4)
    scale = c[0].number_input("Reflectance scale", 0.0, 10.0, float(scale0), format="%.6f", key=f"cl_scale_{preset}")
    offset = c[1].number_input("Offset", -10.0, 10.0, float(off0), format="%.4f", key=f"cl_off_{preset}")
    extra = c[2].multiselect("Extra layers (DEM, SAR, slope...)", [r for r in R if r not in band_map.values()], key="cl_extra")
    texture = c[3].checkbox("Texture (5×5 std of NIR / NDVI)", key="cl_tex")
    avail = classify.available_indices(band_map)
    indices = st.multiselect("Spectral indices as features", avail, default=[i for i in ("NDVI", "MNDWI", "NDBI", "BSI") if i in avail], key="cl_idx")

    ui.section("🌈", "Spectral index maps", "Write the selected indices as GeoTIFFs (also added to the session layers)", "green")
    if st.button("🌈 Create index rasters") and indices:
        res = ctx.call("spectral_indices", {"band_map": band_map, "indices": indices, "scale": scale, "offset": offset,
                                            "prefix": (stack or "img").rsplit(".", 1)[0] + "_"})
        if "error" in res:
            st.error(res["error"])
        else:
            st.session_state.cl_idx_res = res
            st.rerun()
    if st.session_state.get("cl_idx_res"):
        st.dataframe(pd.DataFrame(st.session_state.cl_idx_res["indices"]), hide_index=True)

    ui.section("🧠", "Supervised classification", "Train, cross-validate (random vs spatial blocks), map with confidence", "violet")
    T = list(ctx.tables)
    if not T:
        st.info("Upload a training CSV with x, y and an integer class column in the sidebar.")
    else:
        tb = st.selectbox("Training table", T, key="cl_tb")
        tcols = list(ctx.tables[tb].columns)
        guess = lambda keys, d=0: next((tcols.index(x) for x in tcols if x.lower() in keys), min(d, len(tcols) - 1))  # noqa: E731
        c = st.columns(4)
        cc = c[0].selectbox("Class column", tcols, index=guess({"class", "cls", "code", "lulc", "label", "reference", "reference_class"}, 2), key="cl_cc")
        xc = c[1].selectbox("X column", tcols, index=guess({"x", "lon", "longitude", "easting"}), key="cl_xc")
        yc = c[2].selectbox("Y column", tcols, index=guess({"y", "lat", "latitude", "northing"}, 1), key="cl_yc")
        epsg = c[3].number_input("Point EPSG (0 = same as image)", 0, 99999, 4326 if xc.lower() in ("lon", "longitude") else 0, key="cl_epsg")
        c = st.columns(5)
        model = c[0].selectbox("Classifier", classify.MODELS, key="cl_model")
        trees = c[1].number_input("Trees / iterations", 20, 2000, 150, 10, key="cl_trees", help="~7 s per million pixels at 100 trees; more trees rarely help beyond 150-300.")
        block = c[2].number_input("CV block size (m)", 30.0, 100000.0, 1000.0, 100.0, key="cl_block",
                                  help="Should exceed the range of spatial autocorrelation of your training samples.")
        folds = c[3].number_input("Folds", 2, 10, 5, key="cl_folds")
        smooth = c[4].selectbox("Majority filter", [0, 3, 5, 7], key="cl_smooth", help="Removes isolated pixels (0 = off).")
        out = st.text_input("Output map name", f"LULC_{model.split()[0]}.tif", key="cl_out")
        labels = _labels("cl_lab")
        if st.button("🧠 Train, validate and classify", type="primary"):
            with st.spinner("Training and mapping…"):
                res = ctx.call("classify_image", {
                    "table": tb, "class_column": cc, "x_column": xc, "y_column": yc, "epsg": int(epsg) or None,
                    "band_map": band_map, "extra_layers": extra, "indices": indices, "texture": texture, "scale": scale, "offset": offset,
                    "model": model, "n_trees": int(trees), "block_m": block, "folds": int(folds), "smooth": int(smooth),
                    "output_name": out, "labels": labels})
            st.session_state.cl_res = (res, labels)
            st.rerun()
    if st.session_state.get("cl_res"):
        res, labels = st.session_state.cl_res
        if "error" in res:
            st.error(res["error"])
        else:
            for w in res["warnings"]:
                st.warning(w)
            cv = res["cross_validation"]
            c = st.columns(2)
            with c[0]:
                if "random_kfold" in cv:
                    _cv_block("Random stratified k-fold", cv["random_kfold"])
            with c[1]:
                if "spatial_block_kfold" in cv:
                    _cv_block("Spatial block k-fold (report this)", cv["spatial_block_kfold"])
            if "optimism_gap_oa" in cv:
                st.caption(f"Optimism of random CV: {100 * cv['optimism_gap_oa']:+.1f} percentage points of overall accuracy.")
            sp = cv.get("spatial_block_kfold") or cv.get("random_kfold")
            cls = [str(k) for k in sp["classes"]]
            names = [f"{k} {(labels or {}).get(k, '')}".strip() for k in cls]
            c = st.columns(2)
            c[0].markdown("**Per class (spatial CV)**")
            c[0].dataframe(pd.DataFrame({"class": names, "producer's": sp["producers_accuracy"], "user's": sp["users_accuracy"], "F1": sp["f1"]}).round(3), hide_index=True)
            c[1].markdown("**Confusion matrix** (rows reference, columns predicted)")
            c[1].dataframe(pd.DataFrame(sp["confusion_matrix_rows_reference_cols_predicted"], index=names, columns=names))
            imp = pd.DataFrame(res["feature_importance"])
            st.altair_chart(alt.Chart(imp).mark_bar(color="#8B5CF6").encode(
                x=alt.X("importance:Q", title="Permutation importance (drop in accuracy)"), y=alt.Y("feature:N", sort="-x", title=None),
                tooltip=["feature", alt.Tooltip("importance:Q", format=".4f"), alt.Tooltip("std:Q", format=".4f")]).properties(height=22 * len(imp) + 20),
                use_container_width=True)
            st.caption(f"{res['training_pixels']} training pixels ({res['points_dropped']} points dropped: outside image, NoData or duplicates). "
                       f"Per class: {res['per_class_training']}. {res['note']}")
            pr = res.get("prediction")
            if pr:
                c = st.columns(2)
                with c[0]:
                    st.markdown(f"**{pr['output']}**")
                    _show(ctx.store.outputs[pr["output"]], labels=labels)
                    st.download_button(f"⬇️ Download {pr['output']}", ctx.store.outputs[pr["output"]], pr["output"], "image/tiff", key="dl_cl_map")
                if pr.get("confidence_output") in ctx.store.outputs:
                    with c[1]:
                        st.markdown(f"**Confidence** · mean {pr['mean_confidence']:.2f}, {100 * pr['low_confidence_share']:.1f}% of pixels < 0.5")
                        _show(ctx.store.outputs[pr["confidence_output"]], continuous=True)
                        st.download_button("⬇️ Download confidence", ctx.store.outputs[pr["confidence_output"]], pr["confidence_output"], "image/tiff", key="dl_cl_conf")
                if pr.get("class_area_ha"):
                    st.dataframe(pd.DataFrame({"class": [f"{k} {(labels or {}).get(str(k), '')}".strip() for k in pr["class_area_ha"]],
                                               "pixels": list(pr["class_pixels"].values()), "area_ha (pixel count)": list(pr["class_area_ha"].values())}), hide_index=True)
                st.success("The map was added to the session layers: use it in Accuracy, Area-adjusted accuracy, Intensity, Landscape and the Live canvas.")

    ui.section("🎲", "Unsupervised clustering", "K-means on the same feature stack, for exploring spectral classes", "orange")
    c = st.columns(3)
    k = c[0].number_input("Clusters", 2, 30, 8, key="km_k")
    kout = c[1].text_input("Output name", "kmeans_clusters.tif", key="km_out")
    if c[2].button("🎲 Run K-means"):
        with st.spinner("Clustering…"):
            res = ctx.call("cluster_image", {"band_map": band_map, "extra_layers": extra, "indices": indices, "texture": texture,
                                             "scale": scale, "offset": offset, "k": int(k), "output_name": kout})
        st.session_state.km_res = res
        st.rerun()
    if st.session_state.get("km_res"):
        res = st.session_state.km_res
        if "error" in res:
            st.error(res["error"])
        elif res["output"] in ctx.store.outputs:
            _show(ctx.store.outputs[res["output"]])
            st.caption(res["note"])
            st.download_button(f"⬇️ Download {res['output']}", ctx.store.outputs[res["output"]], res["output"], "image/tiff", key="dl_km")
