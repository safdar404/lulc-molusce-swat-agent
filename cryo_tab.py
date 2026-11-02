"""Streamlit tab (v1.4.0): hypsometry, snow / ice mapping and elevation-zone statistics for mountain basins."""
import altair as alt
import pandas as pd
import streamlit as st

import classify
import ui
from classify_tab import _show


def _zones(txt):
    try:
        z = [float(x) for x in txt.replace(";", ",").split(",") if x.strip()]
        return sorted(z) or None
    except ValueError:
        st.warning("Zone limits must be numbers separated by commas, e.g. 2500, 3500, 4500, 5500.")
        return None


def _prefer(key, options, good):
    """Streamlit keeps a selectbox's earlier value after new layers arrive (the composite stayed selected as 'DEM' once the DEM was
    downloaded). Switch to the first suitable option when the remembered value is not suitable (v1.4.6)."""
    cur = st.session_state.get(key)
    best = next((o for o in options if good(o)), None)
    if best is not None and (cur not in options or not good(cur)):
        st.session_state[key] = best


def _clip_select(ctx, key):
    vs = ctx.__dict__.get("vectors", {})
    v = st.selectbox("Clip to basin polygon", ["(none)"] + list(vs), index=1 if vs else 0, key=key)
    return None if v == "(none)" else v


def render(ctx, R):
    maps = [r for r in R if "#" not in r]
    ui.section("🏔️", "Hypsometry and elevation zones", "Area per elevation band, hypsometric curve and integral, custom snowmelt zones", "blue")
    if not maps:
        st.info("Load or download a DEM (🌍 Download imagery → Copernicus DEM) and upload the basin boundary (KMZ, shapefile, GeoPackage).")
        return
    dems = [m for m in maps if "dem" in m.lower()] + [m for m in maps if "dem" not in m.lower()]
    is_dem = lambda n: "dem" in n.lower()  # noqa: E731
    _prefer("cy_dem", dems, is_dem)
    _prefer("cy_dem2", dems, is_dem)
    c = st.columns(4)
    dem = c[0].selectbox("DEM", dems, key="cy_dem")
    band = c[1].number_input("Band width (m)", 50.0, 2000.0, 500.0, 50.0, key="cy_band")
    zt = c[2].text_input("Zone limits (m, optional)", "", placeholder="2500, 3500, 4500, 5500", key="cy_zones")
    with c[3]:
        clip = _clip_select(ctx, "cy_clip")
    if st.button("🏔️ Compute hypsometry"):
        st.session_state.cy_h = ctx.call("hypsometry", {"dem": dem, "band_m": band, "zones": _zones(zt), "clip_vector": clip})
    h = st.session_state.get("cy_h")
    if h and "error" in h:
        st.error(h["error"])
    elif h:
        m = st.columns(5)
        m[0].metric("Area", f"{h['area_km2']:,.0f} km²")
        m[1].metric("Elevation range", f"{h['min_m']:,.0f}–{h['max_m']:,.0f} m")
        m[2].metric("Mean / median", f"{h['mean_m']:,.0f} / {h['median_m']:,.0f} m")
        m[3].metric("Hypsometric integral", f"{h['hypsometric_integral']:.3f}")
        m[4].metric("5–95 % of area", f"{h['percentiles_m']['p5']:,.0f}–{h['percentiles_m']['p95']:,.0f} m")
        b = pd.DataFrame(h["bands"])
        b["band"] = b["from_m"].astype(int).astype(str) + "–" + b["to_m"].astype(int).astype(str)
        b["mid"] = (b["from_m"] + b["to_m"]) / 2
        b["zero"] = 0.0
        bars = alt.Chart(b).mark_rect(color="#15803D", opacity=0.85, stroke="white", strokeWidth=0.5).encode(
            y=alt.Y("from_m:Q", title="Elevation (m)"), y2="to_m:Q", x=alt.X("zero:Q", title="Area per band (km², green bars)"), x2="area_km2:Q",
            tooltip=["band", alt.Tooltip("area_km2:Q", format=",.1f"), alt.Tooltip("area_pct:Q", format=".1f")])
        curve = alt.Chart(b).mark_line(color="#DC2626", point=alt.OverlayMarkDef(color="#DC2626", shape="diamond", size=60)).encode(
            y="to_m:Q", x=alt.X("cumulative_km2:Q", title="Cumulative area (km², red curve)", axis=alt.Axis(orient="top")),
            tooltip=["to_m", alt.Tooltip("cumulative_km2:Q", format=",.0f")])
        st.altair_chart(alt.layer(bars, curve).resolve_scale(x="independent").properties(height=400), use_container_width=True)
        st.dataframe(b.drop(columns=["mid", "zero"]), hide_index=True)
        st.caption(h["note"])

    ui.section("❄️", "Snow and ice mapping", "NDSI > 0.4 and NIR > 0.11 on a composite (Hall et al. 1995)", "violet")
    stacks = [n for n in maps if ctx.store.band_count(n) > 1]
    if not stacks:
        st.info("Download a Sentinel-2 or Landsat composite first (🌍 Download imagery). For snow cover pick a narrow date window; "
                "a late-summer window (Aug–Sep) approximates glaciers and perennial snow.")
    else:
        c = st.columns(4)
        stk = c[0].selectbox("Composite", stacks, key="cy_stk")
        presets = [p for p in classify.PRESETS if classify.PRESETS[p]["bands"]]
        guess = 0 if "s2" in stk.lower() or "sentinel" in stk.lower() else next((i for i, p in enumerate(presets) if "Downloaded Landsat" in p), 0)
        pre = c[1].selectbox("Band order", presets, index=guess, key="cy_pre")
        thr = c[2].number_input("NDSI threshold", 0.0, 1.0, 0.4, 0.05, key="cy_thr")
        nir = c[3].number_input("NIR reflectance >", 0.0, 1.0, 0.11, 0.01, key="cy_nir")
        c = st.columns(3)
        water = c[0].selectbox("Mask water with (WorldCover class 80)", ["(none)"] + maps, key="cy_water")
        with c[1]:
            clip2 = _clip_select(ctx, "cy_clip2")
        out = c[2].text_input("Output name", f"snow_ice_{stk.rsplit('.', 1)[0]}.tif", key=f"cy_out_{stk}")
        if st.button("❄️ Map snow and ice"):
            st.session_state.cy_s = ctx.call("map_snow_cover", {"stack": stk, "preset": pre, "ndsi_threshold": thr, "nir_threshold": nir,
                                                                "water_layer": None if water == "(none)" else water, "clip_vector": clip2, "output_name": out})
            st.rerun()
        s = st.session_state.get("cy_s")
        if s and "error" in s:
            st.error(s["error"])
        elif s and s["output"] in ctx.store.outputs:
            m = st.columns(3)
            m[0].metric("Snow / ice", f"{s['snow_ice_km2']:,.1f} km²")
            m[1].metric("Share of mapped area", f"{s['snow_ice_pct']:.1f}%")
            m[2].metric("Mapped area", f"{s['mapped_km2']:,.0f} km²")
            _show(ctx.store.outputs[s["output"]], labels=s["labels"])
            c = st.columns(2)
            c[0].download_button(f"⬇️ {s['output']}", ctx.store.outputs[s["output"]], s["output"], "image/tiff", key="dl_cy_s")
            c[1].download_button(f"⬇️ {s['ndsi_output']}", ctx.store.outputs[s["ndsi_output"]], s["ndsi_output"], "image/tiff", key="dl_cy_n")
            st.caption(s["note"])

    ui.section("📶", "Statistics by elevation zone", "Snow cover, glaciers or land cover per elevation band, and the 50 % snowline", "green")
    c = st.columns(4)
    dem2 = c[0].selectbox("DEM", dems, key="cy_dem2")
    from rasterops import categorical_first, is_categorical
    lays = [m for m in categorical_first(ctx.store, maps) if m != dem2]

    def _is_class(n):
        try:
            return ctx.store.band_count(n) == 1 and is_categorical(ctx.store.get(n)) and "dem" not in n.lower()
        except Exception:  # noqa: BLE001
            return False
    _prefer("cy_lay", lays, _is_class)
    lay = c[1].selectbox("Class map", lays, key="cy_lay")
    band2 = c[2].number_input("Band width (m)", 50.0, 2000.0, 500.0, 50.0, key="cy_band2")
    zt2 = c[3].text_input("Zone limits (m, optional)", "", placeholder="2500, 3500, 4500, 5500", key="cy_zones2")
    c = st.columns(3)
    with c[0]:
        clip3 = _clip_select(ctx, "cy_clip3")
    focus = c[1].number_input("Snowline for class code", 0, 255, 1, key="cy_focus")
    if c[2].button("📶 Compute zone statistics"):
        labels = None
        for x in reversed(ctx.__dict__.get("results", [])):
            if isinstance(x["result"], dict) and x["result"].get("output") == lay and x["result"].get("labels"):
                labels = x["result"]["labels"]
                break
        st.session_state.cy_z = ctx.call("elevation_zone_statistics", {"dem": dem2, "layer": lay, "band_m": band2, "zones": _zones(zt2),
                                                                        "clip_vector": clip3, "labels": labels, "focus_class": int(focus)})
    z = st.session_state.get("cy_z")
    if z and "error" in z:
        st.error(z["error"])
    elif z:
        df = pd.DataFrame(z["zones"])
        if z.get("snowline_50pct_m"):
            st.metric(f"50 % line of {z['focus_class']}", f"{z['snowline_50pct_m']:,.0f} m")
        pct = [cc for cc in df.columns if cc.startswith("% ")]
        long = df.melt(id_vars="zone", value_vars=pct, var_name="class", value_name="pct")
        long["class"] = long["class"].str[2:]
        st.altair_chart(alt.Chart(long).mark_bar().encode(y=alt.Y("zone:N", sort=None, title=None), x=alt.X("pct:Q", stack="normalize", title="share of zone"),
                                                          color="class:N", tooltip=["zone", "class", alt.Tooltip("pct:Q", format=".1f")]).properties(height=30 * len(df) + 40),
                        use_container_width=True)
        st.dataframe(df, hide_index=True)
        if z.get("note"):
            st.caption(z["note"])
