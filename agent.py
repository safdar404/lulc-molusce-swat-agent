"""Anthropic tool-use loop for the web app."""
import json, os
import agent_tools

DEFAULT_MODEL = os.environ.get("LULC_AGENT_MODEL", "claude-sonnet-5-5")  # set LULC_AGENT_MODEL or the sidebar field if needed
SYSTEM_PROMPT = """You are a senior geospatial research assistant for a PhD workflow:
satellite imagery -> LULC classification -> change detection -> MOLUSCE simulation -> SWAT+ hydrology -> scenarios -> thesis.
Rules:
1. Never state a numeric result unless a tool returned it in this conversation. Never invent file contents, accuracies or parameters.
2. Inspect before you analyse: start with list_session, inspect_raster, describe_table and check_geometry_match.
3. Enforce scientific order: accuracy assessment before change detection; MOLUSCE hindcasting before future scenarios; SWAT calibration then independent validation with frozen parameters; hold climate constant to isolate LULC effects.
4. MOLUSCE ANN/CA runs and QSWAT+ delineation happen in the user's own software. You prepare, check and evaluate around them; you do not run them. Use record_model_settings to log what the user reports.
5. Report units, CRS, class codes and sample sizes with every statistic. State uncertainty and limitations. Call outputs simulated or scenario-based, never certain.
6. When teaching, cite the practical number, deliverable and a viva question.
7. For accuracy reporting use area_adjusted_accuracy (Olofsson 2014: error-adjusted areas with 95% CI), not kappa alone. Without validation points, use design_accuracy_sample then generate_sample_points.
8. For change between 2+ dates run intensity_analysis after the accuracy check; explain fast/slow intervals, active/dormant categories and targeted transitions, and flag alternation as possible map error.
9. For fragmentation or spatial pattern use landscape_metrics (compare dates on one grid and legend); for where change concentrates use hotspot_analysis and report block size, neighbourhood and FDR setting, testing more than one scale.
10. To make a LULC map use classify_image (stack + preset, NDVI/MNDWI/NDBI/BSI indices, Random Forest by default) and report the spatial-block CV accuracy; then recommend independent validation with design_accuracy_sample and area_adjusted_accuracy. Multi-band files expose bands as 'file.tif#k'.
11. For future LULC: driver_analysis first, then simulate_lulc in hindcast mode (validate_against the latest observed map, compare_with any MOLUSCE output) and only then future scenarios. Report FoM and Kappa simulation against the null model, and present scenarios as conditional what-ifs.
12. To link LULC to hydrology: swat_landuse_lookup for QSWAT+, then curve_number_runoff and rusle_erosion to compare scenarios under identical rainfall/soils; for SWAT+ output use flow_evaluation (with warm-up and a calibration/validation split, report Moriasi ratings) and lulc_flow_attribution for runs that differ only in land use.
13. Vector layers (list_session shows them): rasterize_vector turns roads/rivers/protected areas/soils into rasters for drivers, masks and SWAT+; vector_training_samples turns class polygons into training pixels (report polygon-grouped CV); zonal_statistics summarises maps per sub-basin or district; polygonize_raster exports maps to QGIS.
14. When the user wants a write-up, run generate_report after the analyses (it uses the latest result of each tool) and tell them to download it in the Log & report tab.
15. If the user has no imagery, use search_scenes then download_composite (and download_dem / download_worldcover with template = the composite so grids align); Sentinel-2 for 2017 onwards, Landsat 5/7/8/9 for earlier dates.
16. For mountain basins: hypsometry (clip_vector = basin), map_snow_cover on season-specific composites, and elevation_zone_statistics for snow/ice per zone and the snowline. Download layers with vector = basin and clip_vector = basin so statistics cover the basin only.
17. Be concise. If information is missing, ask one clear question."""


def run_agent(api_key, model, messages, session, user_text, max_rounds=10):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    start = len(messages)
    messages.append({"role": "user", "content": user_text})
    try:
        return _loop(client, model, messages, session, max_rounds)
    except Exception:
        del messages[start:]  # keep the conversation valid for the next question
        raise


def _loop(client, model, messages, session, max_rounds):
    events = []
    for _ in range(max_rounds):
        resp = client.messages.create(model=model, max_tokens=2048, system=SYSTEM_PROMPT, tools=agent_tools.schemas(), messages=messages)
        content = []
        for b in resp.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        messages.append({"role": "assistant", "content": content})
        results = []
        for b in content:
            if b["type"] == "text" and b["text"].strip():
                events.append(("assistant", b["text"]))
            elif b["type"] == "tool_use":
                events.append(("tool", f"{b['name']}({json.dumps(b['input'], default=str)[:200]})"))
                out = agent_tools.run_tool(session, b["name"], b["input"])
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out, default=str)[:6000]})
        if not results:
            return events
        messages.append({"role": "user", "content": results})
    events.append(("error", "Stopped after the maximum number of tool rounds."))
    return events


def friendly_error(e):
    """Turn API errors into a short explanation the user can act on."""
    msg, name = str(e), type(e).__name__
    low = msg.lower()
    if "credit balance" in low:
        return ("**The Anthropic account behind this API key has no credit left**, so the AI agent cannot answer right now. "
                "Add credit under *Plans & Billing* at console.anthropic.com, or use another key. "
                "Below is the built-in analysis, which does not need the API.")
    if name == "AuthenticationError" or "invalid x-api-key" in low:
        return "**The API key was rejected.** Check it in the sidebar (it starts with `sk-ant-`). Below is the built-in analysis instead."
    if name == "NotFoundError" or "model" in low and "not found" in low:
        return "**The model name was not recognised.** Change the *Model* field in the sidebar. Below is the built-in analysis instead."
    if name == "RateLimitError" or "rate limit" in low:
        return "**The API rate limit was reached.** Wait a minute and ask again. Below is the built-in analysis instead."
    if name in ("APIConnectionError", "APITimeoutError", "InternalServerError", "OverloadedError") or "overloaded" in low:
        return "**The model service is busy or unreachable.** Try again shortly. Below is the built-in analysis instead."
    return f"**The AI agent hit an error** (`{name}`: {msg[:200]}). Below is the built-in analysis instead."


def _fmt(v):
    return f"{v:,.3f}" if isinstance(v, float) else str(v)


def offline_analysis(session):
    """Rule-based summary of everything loaded, built only from audited tools (no model call)."""
    run = agent_tools.run_tool
    out = ["#### ⚡ Built-in analysis (no AI)"]
    inv = run(session, "list_session", {})
    if not inv.get("rasters") and not inv.get("tables"):
        return ("#### ⚡ Built-in analysis (no AI)\nNothing is loaded yet. Upload GeoTIFF rasters or CSV tables in the sidebar, "
                "then use the tabs (Area & transitions, Accuracy, Hindcast, Hydrology) or ask again.")
    for name in inv.get("tables", {}):
        d = run(session, "describe_table", {"table": name})
        if "error" in d:
            out.append(f"- `{name}`: {d['error']}")
            continue
        out.append(f"\n**Table `{name}`**: {d['rows']:,} rows × {d['columns']} columns.")
        if d["missing"]:
            out.append("- Missing values: " + ", ".join(f"`{c}` {n:,}" for c, n in list(d["missing"].items())[:10]))
        if d["numeric_summary"]:
            out.append("\n| column | mean | std | min | max |\n|---|---|---|---|---|")
            for c, st_ in list(d["numeric_summary"].items())[:12]:
                out.append(f"| `{c}` | {_fmt(st_.get('mean'))} | {_fmt(st_.get('std'))} | {_fmt(st_.get('min'))} | {_fmt(st_.get('max'))} |")
        for c, info in list(d["categorical_summary"].items())[:6]:
            top = ", ".join(f"{k} ({v:,})" for k, v in list(info["top"].items())[:5])
            out.append(f"- `{c}`: {info['unique']:,} distinct values; most common: {top}")
        cols = {c.lower() for c in d["dtypes"]}
        hints = []
        if {"x", "y"} <= cols or {"lon", "lat"} <= cols or {"easting", "northing"} <= cols:
            hints.append("it has coordinates, so with a classified raster it can drive the **🎯 Accuracy** and **📏 Area-adjusted accuracy** tabs "
                         "(Olofsson 2014: error-adjusted areas with 95% CI)")
        if any("date" in c or "time" in c for c in cols) and len(d["numeric_summary"]) >= 1:
            hints.append("it has dates and numbers, so observed/simulated series can go to the **Hydrology** tab (NSE, PBIAS, KGE)")
        if hints:
            out.append("- Suggested next step: " + "; ".join(hints) + ".")
    for name in inv.get("rasters", []):
        r = run(session, "inspect_raster", {"layer": name})
        if "error" in r:
            out.append(f"- `{name}`: {r['error']}")
            continue
        cls = f"; classes {r['class_values']}" if r.get("class_values") else ""
        out.append(f"\n**Raster `{name}`**: {r['size_cols_rows'][0]}×{r['size_cols_rows'][1]} px, pixel {abs(r['pixel_size'][0]):g} units, "
                   f"CRS {r['crs']}, values {_fmt(r.get('min'))} to {_fmt(r.get('max'))}{cls}.")
    if len(inv.get("rasters", [])) > 1:
        g = run(session, "check_geometry_match", {"layers": inv["rasters"]})
        if "error" not in g:
            out.append("\n**Geometry check**: " + ("all rasters share one grid, ready for transitions and MOLUSCE. "
                                                    "Next: the **📈 Intensity analysis** tab (fast/slow intervals, active/dormant categories, targeted transitions)."
                                                    if g["all_match"] else "rasters do **not** share one grid; align them before MOLUSCE."))
    out.append("\n_Every figure above comes from the audited tools and is in the Log tab. Verify numbers before they enter a thesis._")
    return "\n".join(out)
