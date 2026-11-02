"""Streamlit tab (v1.1.0): vector layers — describe, rasterize, training samples, zonal statistics, polygonize."""
import json

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import ui
import vectorops as V


def vectors(ctx):
    return ctx.__dict__.setdefault("vectors", {})


def _plot(g, raster=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.6), dpi=110)
    if raster is not None:
        a = raster.data.astype(float)
        a[raster.mask] = np.nan
        t = raster.transform
        ext = (t.c, t.c + t.a * a.shape[1], t.f + t.e * a.shape[0], t.f)
        ax.imshow(a, extent=ext, cmap="Greys", alpha=0.6, interpolation="nearest")
        g = g.to_crs(raster.crs) if raster.crs is not None and g.crs != raster.crs else g
    g.plot(ax=ax, facecolor="none" if g.geom_type.iloc[0].endswith("Polygon") else "#EC4899", edgecolor="#7C3AED", linewidth=0.8, markersize=8)
    ax.set_axis_off()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render(ctx, R):
    vs = vectors(ctx)
    maps = [r for r in R if "#" not in r]
    ui.section("🧭", "Vector layers", "Zipped shapefiles, GeoPackage, GeoJSON or KML from the sidebar; reprojected to the raster CRS on the fly", "blue")
    if not vs:
        st.info("Upload vector files in the sidebar (🧭 Vectors). Zip a shapefile with its .shp, .shx, .dbf and .prj, or upload those parts together.")
        return
    names = list(vs)
    c = st.columns([1, 1])
    v = c[0].selectbox("Vector layer", names, key="vt_v")
    bg = c[1].selectbox("Background raster (optional)", ["(none)"] + maps, key="vt_bg")
    d = ctx.call("describe_vector", {"layer": v})
    if "error" in d:
        st.error(d["error"])
    else:
        m = st.columns(3)
        m[0].metric("Features", f"{d['features']:,}")
        m[1].metric("Geometry", ", ".join(d["geometry_types"]))
        m[2].metric("CRS", d["crs"][:22])
        _plot(vs[v], None if bg == "(none)" else ctx.store.get(bg))
        with st.expander("Attribute table (first 200 rows)"):
            st.dataframe(pd.DataFrame(vs[v].drop(columns="geometry")).head(200), hide_index=True)
    fields = [c_ for c_ in vs[v].columns if c_ != "geometry"]

    ui.section("🧱", "Rasterize onto a raster grid", "Roads, rivers, protected areas, soils or zones as GeoTIFFs for drivers, masks and SWAT+", "green")
    if not maps:
        st.info("Upload a raster to use as the template grid.")
    else:
        c = st.columns(4)
        tpl = c[0].selectbox("Template raster (grid)", maps, key="vt_tpl")
        fld = c[1].selectbox("Value from field", ["(burn 1)"] + fields, key="vt_fld")
        at = c[2].checkbox("All touched cells (thin lines)", value=vs[v].geom_type.iloc[0].endswith("LineString"), key="vt_at")
        out = c[3].text_input("Output name", f"{v}_raster.tif", key=f"vt_out_{v}")
        if st.button("🧱 Rasterize"):
            res = ctx.call("rasterize_vector", {"vector": v, "template": tpl, "field": None if fld == "(burn 1)" else fld, "all_touched": at, "output_name": out})
            st.session_state.vt_ras = res
            st.rerun()
        res = st.session_state.get("vt_ras")
        if res and "error" in res:
            st.error(res["error"])
        elif res:
            st.success(f"{res['output']} added to the session layers ({res['burned_pixels']:,} pixels). Use it as a driver, protected mask, HSG or zone raster.")
            if res.get("code_lookup"):
                st.dataframe(pd.DataFrame({"value": list(res["code_lookup"]), "code": list(res["code_lookup"].values())}), hide_index=True)

        ui.section("🎯", "Training or validation samples from vectors", "Polygons → pixel samples with polygon IDs; points → table", "orange")
        c = st.columns(4)
        tpl2 = c[0].selectbox("Image / grid", maps, key="vt_tpl2")
        cf = c[1].selectbox("Class field", fields or ["(none)"], key="vt_cf")
        mx = c[2].number_input("Max pixels per class", 50, 100000, 2000, 50, key="vt_mx")
        tn = c[3].text_input("Table name", f"{v}_samples.csv", key=f"vt_tn_{v}")
        is_pt = set(vs[v].geom_type.unique()) <= {"Point", "MultiPoint"}
        if st.button("🎯 Create samples"):
            if is_pt:
                res = ctx.call("vector_points_to_table", {"vector": v, "template": tpl2, "table_name": tn})
            else:
                res = ctx.call("vector_training_samples", {"vector": v, "template": tpl2, "class_field": cf, "max_per_class": int(mx), "table_name": tn})
            st.session_state.vt_smp = res
            st.rerun()
        res = st.session_state.get("vt_smp")
        if res and "error" in res:
            st.error(res["error"])
        elif res:
            st.success(f"Table `{res['table']}` with {res['rows']:,} rows is ready in the Classification / Accuracy tabs (x, y in the raster CRS).")
            if res.get("per_class"):
                st.dataframe(pd.DataFrame({"class": list(res["per_class"]), "pixels": list(res["per_class"].values())}), hide_index=True)
            if res.get("code_lookup"):
                st.caption("Class codes: " + ", ".join(f"{k} = {c_}" for k, c_ in res["code_lookup"].items()))
            st.caption(res.get("note", ""))

        ui.section("📊", "Zonal statistics", "LULC composition or raster statistics per polygon (sub-basins, districts, buffers)", "violet")
        c = st.columns(3)
        zr = c[0].selectbox("Raster", maps, key="vt_zr")
        zf = c[1].selectbox("Zone name field", ["(feature number)"] + fields, key="vt_zf")
        lab_txt = c[2].text_input('Class names JSON (optional)', key="vt_zl")
        if st.button("📊 Compute zonal statistics"):
            try:
                labs = json.loads(lab_txt) if lab_txt.strip() else None
            except Exception:
                labs = None
            st.session_state.vt_zon = ctx.call("zonal_statistics", {"vector": v, "raster": zr, "zone_field": None if zf == "(feature number)" else zf,
                                                                    "labels": labs})
        res = st.session_state.get("vt_zon")
        if res and "error" in res:
            st.error(res["error"])
        elif res:
            df = ctx.tables.get(res["table"])
            if df is not None:
                st.dataframe(df, hide_index=True)
                pct = [c_ for c_ in df.columns if c_.startswith("%")]
                if res["categorical"] and pct and len(df) <= 60:
                    long = df.melt(id_vars="zone", value_vars=pct, var_name="class", value_name="pct")
                    st.altair_chart(alt.Chart(long).mark_bar().encode(y=alt.Y("zone:N", title=None, sort=None), x=alt.X("pct:Q", stack="normalize", title="share"),
                                                                      color="class:N", tooltip=["zone", "class", "pct"]), use_container_width=True)
                st.download_button("⬇️ Zonal table (CSV)", df.to_csv(index=False), res["table"], "text/csv", key="dl_zon")

    ui.section("🔷", "Polygonize a raster", "Classified maps, hotspot clusters or change maps to GeoPackage / GeoJSON for QGIS", "pink")
    if maps:
        c = st.columns(4)
        pr = c[0].selectbox("Categorical raster", maps, key="vt_pr")
        ig = c[1].number_input("Ignore value (-1 = none)", -1, 65535, -1, key="vt_ig")
        sm = c[2].number_input("Simplify tolerance (m)", 0.0, 1000.0, 0.0, key="vt_sm")
        on = c[3].text_input("Layer name", f"{pr.rsplit('.', 1)[0]}_polygons", key=f"vt_on_{pr}")
        if st.button("🔷 Polygonize"):
            st.session_state.vt_pol = ctx.call("polygonize_raster", {"layer": pr, "ignore_value": None if ig < 0 else int(ig), "simplify": sm, "output_name": on})
        res = st.session_state.get("vt_pol")
        if res and "error" in res:
            st.error(res["error"])
        elif res and res["layer"] in vs:
            g = vs[res["layer"]]
            st.caption(f"{res['features']:,} polygons. The layer is also available above for zonal statistics.")
            c = st.columns(2)
            c[0].download_button("⬇️ GeoPackage", V.to_bytes(g, "gpkg"), f"{res['layer']}.gpkg", "application/geopackage+sqlite3", key="dl_pol_gpkg")
            c[1].download_button("⬇️ GeoJSON (WGS84)", V.to_bytes(g, "geojson"), f"{res['layer']}.geojson", "application/geo+json", key="dl_pol_gj")
