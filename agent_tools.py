"""Audited, read-only tools shared by the Streamlit UI and the LLM agent. Nothing touches the file system."""
import json
import changeops, hydro, knowledge, rasterops

REG = {}
S = lambda t, d, **k: dict(type=t, description=d, **k)
STR = lambda d: S("string", d)


def tool(name, desc, props, required=()):
    def deco(fn):
        REG[name] = dict(fn=fn, schema=dict(name=name, description=desc,
                                             input_schema=dict(type="object", properties=props, required=list(required))))
        return fn
    return deco


def schemas():
    return [v["schema"] for v in REG.values()]


@tool("list_session", "List loaded rasters and tables in this session.", {})
def list_session(ctx):
    return dict(rasters=ctx.store.names(), tables={k: list(v.columns) for k, v in ctx.tables.items()}, outputs=list(ctx.store.outputs))


@tool("describe_table", "Rows, columns, data types, missing values, numeric statistics and top categories of one uploaded CSV table.",
      {"table": STR("Table name")}, ["table"])
def _describe(ctx, table):
    if table not in ctx.tables:
        raise ValueError(f"Table not loaded: {table}. Loaded: {list(ctx.tables)}")
    df = ctx.tables[table]
    num = df.select_dtypes("number")
    cats = {}
    for c in df.columns.difference(num.columns)[:15]:
        vc = df[c].astype(str).value_counts()
        cats[c] = dict(unique=int(vc.size), top=vc.head(5).to_dict())
    return dict(table=table, rows=int(len(df)), columns=int(df.shape[1]),
                dtypes={c: str(t) for c, t in df.dtypes.items()},
                missing={c: int(n) for c, n in df.isna().sum().items() if n},
                numeric_summary=num.describe().T.round(4).to_dict(orient="index") if not num.empty else {},
                categorical_summary=cats)


@tool("inspect_raster", "CRS, size, pixel size, origin, NoData, min/max and class values of one raster.", {"layer": STR("Raster name")}, ["layer"])
def _inspect(ctx, layer):
    return rasterops.inspect(ctx.store, layer)


@tool("check_geometry_match", "MOLUSCE geometry checklist vs the first (reference) raster: CRS, cell size, rows/cols, origin, NoData mask.",
      {"layers": S("array", "Reference first, then others", items={"type": "string"})}, ["layers"])
def _geom(ctx, layers):
    return rasterops.geometry_match(ctx.store, layers)


@tool("lulc_area_stats", "Class pixel counts, hectares and shares for one LULC raster (projected CRS in metres required).",
      {"layer": STR("LULC raster"), "labels": S("object", "Optional {code: name}")}, ["layer"])
def _area(ctx, layer, labels=None):
    return rasterops.area_stats(ctx.store, layer, labels)


@tool("transition_matrix", "From-to transition matrix (ha) between two LULC rasters on the same grid, with persistence and top conversions.",
      {"old_layer": STR("Earlier"), "new_layer": STR("Later")}, ["old_layer", "new_layer"])
def _trans(ctx, old_layer, new_layer):
    return rasterops.transition_matrix(ctx.store, old_layer, new_layer)


@tool("accuracy_assessment", "Confusion matrix, overall/user's/producer's accuracy and kappa from validation points in an uploaded CSV table.",
      {"raster": STR("Classified raster"), "table": STR("Table name"), "reference_column": STR("Reference class column"),
       "x_column": STR("X/easting or lon"), "y_column": STR("Y/northing or lat"), "epsg": S("integer", "EPSG of the point coordinates if different from the raster")},
      ["raster", "table", "reference_column", "x_column", "y_column"])
def _acc(ctx, raster, table, reference_column, x_column, y_column, epsg=None):
    if table not in ctx.tables:
        raise ValueError(f"Table not loaded: {table}")
    return rasterops.accuracy_points(ctx.store, raster, ctx.tables[table], reference_column, x_column, y_column, epsg)


@tool("hindcast_validation", "Compare simulated vs observed LULC: accuracy, kappa, quantity/allocation disagreement and figure of merit (if initial given).",
      {"observed": STR("Observed raster"), "simulated": STR("Simulated raster"), "initial": STR("Optional initial raster")}, ["observed", "simulated"])
def _hind(ctx, observed, simulated, initial=None):
    return rasterops.hindcast(ctx.store, observed, simulated, initial)


@tool("hydro_metrics", "NSE, PBIAS (obs-sim), R2, KGE from observed/simulated discharge tables.",
      {"observed_table": STR("Table with observed values"), "simulated_table": STR("Table with simulated values (may be the same)"),
       "date_column": STR("Date column"), "observed_column": STR("Observed column"), "simulated_column": STR("Simulated column"),
       "start": STR("Optional ISO start"), "end": STR("Optional ISO end")},
      ["observed_table", "simulated_table", "date_column", "observed_column", "simulated_column"])
def _hydro(ctx, observed_table, simulated_table, date_column, observed_column, simulated_column, start=None, end=None):
    for t in (observed_table, simulated_table):
        if t not in ctx.tables:
            raise ValueError(f"Table not loaded: {t}")
    return hydro.compute(ctx.tables[observed_table], ctx.tables[simulated_table], date_column, observed_column, simulated_column, start, end)


@tool("spectral_index", "Create NDVI, NDWI or NDBI (downloadable output). band_a is the first operand: NIR for NDVI, Green for NDWI, SWIR for NDBI; band_b: Red for NDVI, NIR for NDWI/NDBI.",
      {"index": S("string", "NDVI, NDWI or NDBI", enum=["NDVI", "NDWI", "NDBI"]), "band_a": STR("First operand raster"),
       "band_b": STR("Second operand raster"), "output_name": STR("Output file name, e.g. NDVI_2020.tif")}, ["index", "band_a", "band_b", "output_name"])
def _idx(ctx, index, band_a, band_b, output_name):
    return rasterops.spectral_index(ctx.store, index, band_a, band_b, output_name)


@tool("transition_raster", "Encode transitions old*multiplier+new as a downloadable GeoTIFF.",
      {"old_layer": STR("Earlier"), "new_layer": STR("Later"), "output_name": STR("Output file name"), "multiplier": S("integer", "Default 10")},
      ["old_layer", "new_layer", "output_name"])
def _tr(ctx, old_layer, new_layer, output_name, multiplier=10):
    return rasterops.transition_raster(ctx.store, old_layer, new_layer, output_name, multiplier)


@tool("disagreement_raster", "Map of simulated vs observed disagreement (1) as a downloadable GeoTIFF.",
      {"observed": STR("Observed"), "simulated": STR("Simulated"), "output_name": STR("Output file name")}, ["observed", "simulated", "output_name"])
def _dis(ctx, observed, simulated, output_name):
    return rasterops.disagreement_raster(ctx.store, observed, simulated, output_name)


@tool("practical_guide", "Look up practical 1-30 or search by keyword: deliverable and a viva question.", {"query": STR("Number or keyword")}, ["query"])
def _guide(ctx, query):
    return knowledge.guide(query)


@tool("record_model_settings", "Record settings the user entered in MOLUSCE or SWAT+/QSWAT+ (ANN parameters, thresholds, calibration iterations) in the log.",
      {"stage": STR("e.g. MOLUSCE ANN"), "settings": S("object", "Key-value settings"), "note": STR("Reason or observation")}, ["stage", "settings"])
def _rec(ctx, stage, settings, note=""):
    return dict(recorded=True, stage=stage)


# ---------------- v0.6.0: area-adjusted accuracy and intensity analysis ----------------
LAYERS = S("array", "LULC rasters in date order (oldest first)", items={"type": "string"})
UNIT = S("string", "Area unit", enum=["ha", "km2", "m2"])


@tool("area_adjusted_accuracy", "Good-practice accuracy (Olofsson et al. 2014): area-weighted error matrix, overall/user's/producer's accuracy with 95% CI, "
      "error-adjusted class areas with 95% CI, quantity/allocation/exchange/shift disagreement and a ready methods paragraph. Prefer this over accuracy_assessment for reporting.",
      {"raster": STR("Classified raster"), "table": STR("Validation table"), "reference_column": STR("Reference class column"),
       "x_column": STR("X/easting or lon"), "y_column": STR("Y/northing or lat"), "epsg": S("integer", "EPSG of the points if different from the raster"),
       "unit": UNIT, "labels": S("object", "Optional {code: name}")},
      ["raster", "table", "reference_column", "x_column", "y_column"])
def _aaa(ctx, raster, table, reference_column, x_column, y_column, epsg=None, unit="ha", labels=None):
    if table not in ctx.tables:
        raise ValueError(f"Table not loaded: {table}")
    return changeops.area_adjusted_accuracy(ctx.store, raster, ctx.tables[table], reference_column, x_column, y_column, epsg, unit, labels)


@tool("design_accuracy_sample", "Plan a stratified random accuracy sample for a classified raster (Olofsson 2014 Eq. 13): total n for a target SE of overall accuracy and per-class allocation.",
      {"raster": STR("Classified raster"), "expected_users_accuracy": S("number", "Prior guess of user's accuracy (0-1), default 0.85"),
       "target_se": S("number", "Target standard error of overall accuracy, default 0.01"),
       "allocation": S("string", "Allocation rule", enum=["olofsson", "proportional", "equal", "neyman"]),
       "min_per_class": S("integer", "Minimum per class, default 50")}, ["raster"])
def _design(ctx, raster, expected_users_accuracy=0.85, target_se=0.01, allocation="olofsson", min_per_class=50):
    return changeops.design_sample(ctx.store, raster, expected_users_accuracy, target_se, allocation, min_per_class)


@tool("generate_sample_points", "Generate stratified random validation points from a classified raster and save them as a session table "
      "(blind interpretation sheet). Use design_accuracy_sample first for the counts.",
      {"raster": STR("Classified raster"), "n_per_class": S("object", "{class code: number of points}"), "seed": S("integer", "Random seed"),
       "table_name": STR("Name of the new table, e.g. accuracy_points.csv")}, ["raster", "n_per_class"])
def _points(ctx, raster, n_per_class, seed=42, table_name="accuracy_points.csv"):
    df = changeops.sample_points(ctx.store, raster, n_per_class, seed)
    ctx.tables[table_name] = df
    return dict(table=table_name, points=len(df), per_class=df["map_class"].value_counts().sort_index().to_dict(),
                note="Interpret reference_class on high-resolution imagery without looking at map_class, then upload the filled CSV.")


@tool("intensity_analysis", "Multi-date Intensity Analysis (Aldwaik & Pontius 2012): interval (fast/slow), category (active/dormant gain and loss) and "
      "transition (targeted/avoided) levels, stationarity across intervals, gross gain/loss/net/swap and alternation. Needs 2+ LULC rasters on one grid.",
      {"layers": LAYERS, "years": S("array", "Year of each raster (guessed from file names if omitted)", items={"type": "number"}),
       "unit": UNIT, "labels": S("object", "Optional {code: name}")}, ["layers"])
def _ia(ctx, layers, years=None, unit="ha", labels=None):
    return changeops.intensity_analysis(ctx.store, layers, years, unit, labels)


@tool("change_frequency_raster", "Downloadable GeoTIFF counting how many intervals each pixel changed in (multi-date LULC series).",
      {"layers": LAYERS, "output_name": STR("Output file name")}, ["layers", "output_name"])
def _cf(ctx, layers, output_name):
    return changeops.change_frequency_raster(ctx.store, layers, output_name)


@tool("trajectory_raster", "Downloadable GeoTIFF of one category's trajectory across 2+ dates (stable, gain/loss with or without alternation; Pontius et al. 2017) with areas.",
      {"layers": LAYERS, "category": S("integer", "Class code"), "output_name": STR("Output file name"), "unit": UNIT},
      ["layers", "category", "output_name"])
def _traj(ctx, layers, category, output_name, unit="ha"):
    return changeops.trajectory_raster(ctx.store, layers, category, output_name, unit)


def run_tool(ctx, name, args):
    t = REG.get(name)
    if not t:
        return dict(error=f"Unknown tool {name}")
    try:
        res = t["fn"](ctx, **(args or {}))
        ctx.record(name, args, json.dumps(res, default=str)[:200], (args or {}).get("note", "") if name == "record_model_settings" else "")
        return res
    except Exception as e:
        return dict(error=f"{type(e).__name__}: {e}")
