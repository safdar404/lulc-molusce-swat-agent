"""Streamlit tab (v0.7.0): landscape pattern metrics, moving-window maps and spatial hotspots."""
import io
import json

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from rasterio.io import MemoryFile

import hotspot
import ui

LAND_HELP = {
    "NP": "number of patches", "PD": "patches per 100 ha", "LPI": "largest patch index (%)", "ED_m_per_ha": "edge density (m/ha)",
    "LSI": "landscape shape index", "AREA_MN_ha": "mean patch area (ha)", "SHAPE_MN": "mean shape index", "FRAC_MN": "mean fractal dimension",
    "ENN_MN_m": "mean nearest-neighbour distance (m)", "CONTAG": "contagion (%)", "SHDI": "Shannon diversity", "SHEI": "Shannon evenness",
    "SIDI": "Simpson diversity", "AI": "aggregation index (%)", "DIVISION": "landscape division", "MESH_ha": "effective mesh size (ha)",
    "COHESION": "patch cohesion", "PR": "patch richness"}


def _labels(key):
    txt = st.text_input('Optional class names as JSON, e.g. {"1": "Water", "2": "Built-up"}', key=key)
    try:
        return json.loads(txt) if txt.strip() else None
    except Exception:
        st.warning("Could not read the class-name JSON; showing codes only.")
        return None


def _xlsx(sheets):
    bio = io.BytesIO()
    try:
        with pd.ExcelWriter(bio) as xw:
            for n, df in sheets.items():
                df.to_excel(xw, sheet_name=n[:31], index=False)
        return bio.getvalue(), "xlsx"
    except ImportError:
        return "\n\n".join(f"# {n}\n{df.to_csv(index=False)}" for n, df in sheets.items()).encode(), "csv"


def _preview(raw, kind):
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    with MemoryFile(raw) as mf, mf.open() as src:
        a = src.read(1).astype(float)
        nd = src.nodata
    if nd is not None:
        a[a == nd] = np.nan
    fig, ax = plt.subplots(figsize=(6, 4.2), dpi=110)
    if kind == "gi":
        cols = ["#2166AC", "#67A9CF", "#D1E5F0", "#F2F2F2", "#FDDBC7", "#EF8A62", "#B2182B"]
        im = ax.imshow(a, cmap=ListedColormap(cols), norm=BoundaryNorm(np.arange(-3.5, 4.5), 7), interpolation="nearest")
        cb = fig.colorbar(im, ax=ax, ticks=range(-3, 4), shrink=0.8)
        cb.ax.set_yticklabels([hotspot.GI_NAMES[i] for i in range(-3, 4)], fontsize=7)
    elif kind == "lisa":
        cols = ["#EEEEEE", "#D7191C", "#ABD9E9", "#2C7BB6", "#FDAE61"]
        im = ax.imshow(a, cmap=ListedColormap(cols), norm=BoundaryNorm(np.arange(-0.5, 5.5), 5), interpolation="nearest")
        cb = fig.colorbar(im, ax=ax, ticks=range(5), shrink=0.8)
        cb.ax.set_yticklabels([hotspot.CLUSTER_NAMES[i] for i in range(5)], fontsize=7)
    else:
        im = ax.imshow(a, cmap="viridis", interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_axis_off()
    fig.tight_layout()
    return fig


def _show(container, raw, kind):
    import matplotlib.pyplot as plt
    fig = _preview(raw, kind)
    container.pyplot(fig)
    plt.close(fig)


def render(ctx, R):
    ui.section("🧩", "Landscape metrics", "FRAGSTATS-definition class and landscape metrics for one or several dates", "green")
    if not R:
        st.info("Upload categorical LULC rasters (projected CRS in metres) in the sidebar.")
        return
    layers = st.multiselect("LULC rasters (one per date)", R, default=R[: min(3, len(R))], key="lm_layers")
    c = st.columns(4)
    nb = c[0].radio("Patch neighbour rule", [8, 4], horizontal=True, key="lm_nb")
    enn = c[3].checkbox("Nearest-neighbour distance (slower)", True, key="lm_enn")
    depth = c[1].number_input("Edge depth for core area (m, 0 = one cell)", 0.0, 10000.0, 0.0, 10.0, key="lm_depth")
    top = c[2].number_input("List largest patches", 0, 100, 10, key="lm_top")
    labels = _labels("lm_lab")
    if layers and st.button("🧩 Compute landscape metrics"):
        st.session_state.lm_res = ctx.call("landscape_metrics", {"layers": layers, "neighbourhood": int(nb), "edge_depth_m": depth or None,
                                                                  "labels": labels, "patches_top": int(top),
                                                                  "nearest_neighbour": bool(enn)})
    res = st.session_state.get("lm_res")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        land = pd.DataFrame(res["landscape"]).set_index("layer")
        st.markdown("**Landscape level**")
        st.dataframe(land.T.rename(index=lambda m: f"{m} · {LAND_HELP[m]}" if m in LAND_HELP else m))
        cls = pd.DataFrame(res["classes"])
        st.markdown("**Class level**")
        metric_cols = [x for x in cls.columns if x not in ("class_code", "class_name", "layer")]
        mcol = st.selectbox("Chart class metric", metric_cols, index=metric_cols.index("PLAND"), key="lm_metric")
        chart = alt.Chart(cls).mark_bar().encode(
            x=alt.X("class_name:N", title=None), xOffset="layer:N", y=alt.Y(f"{mcol}:Q", title=mcol),
            color=alt.Color("layer:N", scale=alt.Scale(range=["#8B5CF6", "#EC4899", "#F97316", "#06B6D4", "#10B981"])),
            tooltip=["layer", "class_name", alt.Tooltip(f"{mcol}:Q", format=",.3f")])
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(cls, hide_index=True)
        if res.get("landscape_change_first_to_last"):
            st.markdown("**Change first → last date**")
            st.dataframe(pd.DataFrame([res["landscape_change_first_to_last"]]), hide_index=True)
        if res.get("largest_patches"):
            with st.expander("Largest patches"):
                for n, rows in res["largest_patches"].items():
                    st.markdown(f"`{n}`")
                    st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption(res["interpretation"])
        data, ext = _xlsx({"landscape": land.reset_index(), "class": cls})
        st.download_button(f"⬇️ Download metrics (.{ext})", data, f"landscape_metrics.{ext}", key="dl_lm")

    ui.section("🪟", "Moving-window map", "Diversity, edge density or class share in a square window, as a GeoTIFF", "blue")
    c = st.columns(4)
    wl = c[0].selectbox("Raster", R, key="mw_layer")
    wm = c[1].selectbox("Metric", ["SHDI", "SIDI", "PR", "ED", "PLAND"], key="mw_metric")
    ws = c[2].number_input("Window side (m)", 30.0, 100000.0, 990.0, 30.0, key="mw_size")
    wc = c[3].number_input("Class code (PLAND)", 0, 65535, 1, key="mw_cls")
    if st.button("🪟 Create moving-window map"):
        name = f"mw_{wm}_{int(ws)}m_{wl.rsplit('.', 1)[0]}.tif"
        out = ctx.call("moving_window_map", {"layer": wl, "metric": wm, "window_m": ws, "class_code": int(wc), "output_name": name})
        if "error" in out:
            st.error(out["error"])
        else:
            st.session_state.mw_last = name
            st.caption(f"Window {out['window_cells']} cells ({out['window_m']:.0f} m). Mean {out['mean']:.3f}, range {out['min']:.3f} to {out['max']:.3f}.")
    if st.session_state.get("mw_last") in ctx.store.outputs:
        n = st.session_state.mw_last
        _show(st, ctx.store.outputs[n], "cont")
        st.download_button(f"⬇️ Download {n}", ctx.store.outputs[n], n, "image/tiff", key="dl_mw")

    ui.section("🔥", "Hotspot analysis", "Getis-Ord Gi* and Local Moran's I (LISA) on a value or on LULC change, aggregated to blocks", "pink")
    c = st.columns(4)
    hl = c[0].selectbox("Raster (earlier map for change)", R, key="hs_layer")
    var = c[1].selectbox("Variable", ["change", "gain", "loss", "presence", "value"], key="hs_var",
                         help="change / gain / loss need a later map; presence = share of a class; value = a continuous raster (e.g. NDVI difference, LST).")
    h2 = c[2].selectbox("Later map", ["(none)"] + R, index=min(2, len(R)) if len(R) > 1 else 0, key="hs_l2")
    hc = c[3].number_input("Class code", 0, 65535, 1, key="hs_cls")
    c = st.columns(5)
    blk = c[0].number_input("Block (cells per side)", 1, 500, 10, key="hs_blk")
    rad = c[1].number_input("Neighbour radius (blocks)", 1, 20, 1, key="hs_rad")
    shp = c[2].selectbox("Window", ["square", "circle"], key="hs_shape")
    meth = c[3].selectbox("Method", ["both", "gi", "lisa"], key="hs_meth")
    perms = c[4].number_input("LISA permutations", 99, 9999, 199, 100, key="hs_perm")
    fdr = st.checkbox("False-discovery-rate correction (recommended)", True, key="hs_fdr")
    if st.button("🔥 Run hotspot analysis"):
        st.session_state.hs_res = ctx.call("hotspot_analysis", {
            "layer": hl, "variable": var, "second_layer": None if h2 == "(none)" else h2, "class_code": int(hc), "block": int(blk),
            "radius": int(rad), "kernel_shape": shp, "method": meth, "fdr": bool(fdr), "permutations": int(perms),
            "output_prefix": f"hotspot_{var}"})
    res = st.session_state.get("hs_res")
    if res and "error" in res:
        st.error(res["error"])
    elif res:
        gm = res["global_moran"]
        m = st.columns(4)
        m[0].metric("Global Moran's I", f"{gm['I']:.3f}" if gm["I"] == gm["I"] else "n/a")
        m[1].metric("z-score", f"{gm['z']:.2f}" if gm["z"] == gm["z"] else "n/a")
        m[2].metric("p-value", f"{gm['p']:.4f}" if gm["p"] == gm["p"] else "n/a")
        m[3].metric("Analysis cells", f"{res['valid_cells']:,}", f"{res['analysis_cell_size']:.0f} m blocks", delta_color="off")
        st.caption(f"Variable: {res['variable']}. Neighbourhood: {res['neighbourhood']}.")
        c = st.columns(2)
        if "gi_star" in res:
            gi = res["gi_star"]
            df = pd.DataFrame({"bin": list(gi["cells_by_bin"]), "cells": list(gi["cells_by_bin"].values())})
            if gi.get("area_ha_by_bin"):
                df["area_ha"] = list(gi["area_ha_by_bin"].values())
            c[0].markdown("**Getis-Ord Gi\\***")
            c[0].dataframe(df, hide_index=True)
            name = next(o for o in res["outputs"] if o.endswith("_gi_bins.tif"))
            _show(c[0], ctx.store.outputs[name], "gi")
            with c[0].expander("Strongest hot and cold spots"):
                st.dataframe(pd.DataFrame(gi["strongest_spots"]), hide_index=True)
        if "lisa" in res:
            li = res["lisa"]
            c[1].markdown("**Local Moran's I (LISA)**")
            if "skipped" in li:
                c[1].warning(li["skipped"])
            else:
                c[1].dataframe(pd.DataFrame({"cluster": list(li["cells_by_cluster"]), "cells": list(li["cells_by_cluster"].values())}), hide_index=True)
                name = next(o for o in res["outputs"] if o.endswith("_lisa_clusters.tif"))
                _show(c[1], ctx.store.outputs[name], "lisa")
        st.caption(res["note"])
        for n in res["outputs"]:
            if n in ctx.store.outputs:
                st.download_button(f"⬇️ Download {n}", ctx.store.outputs[n], n, "image/tiff", key=f"dl_hs_{n}")
