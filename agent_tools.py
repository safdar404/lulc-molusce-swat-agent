"""Audited, read-only tools shared by the Streamlit UI and the LLM agent. Nothing touches the file system."""
import json
import changeops, classify, hydro, knowledge, patternops, rasterops, simulate

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


# ---------------- v0.7.0: landscape pattern and hotspots ----------------
@tool("landscape_metrics", "FRAGSTATS-definition landscape metrics for one or several LULC rasters (dates): class level (CA, PLAND, NP, PD, LPI, TE, ED, LSI, "
      "AREA_MN/AM/CV, SHAPE, FRAC, ENN, core area, AI, COHESION, DIVISION, MESH, SPLIT) and landscape level (plus CONTAG, SHDI, SHEI, SIDI, PR). "
      "Use to quantify fragmentation and aggregation and how they changed between dates.",
      {"layers": S("array", "LULC rasters, one per date", items={"type": "string"}), "neighbourhood": S("integer", "Patch rule 8 (default) or 4"),
       "edge_depth_m": S("number", "Edge depth for core area in metres (default one cell)"), "labels": S("object", "Optional {code: name}"),
       "patches_top": S("integer", "Also list the N largest patches"),
       "nearest_neighbour": S("boolean", "Compute ENN (slowest metric on large rasters; default true)")}, ["layers"])
def _lm(ctx, layers, neighbourhood=8, edge_depth_m=None, labels=None, patches_top=0, nearest_neighbour=True):
    return patternops.landscape_metrics(ctx.store, layers, neighbourhood, edge_depth_m, labels, patches_top, nearest_neighbour)


@tool("moving_window_map", "Moving-window landscape metric raster (SHDI, SIDI, PR, ED or PLAND of one class) as a downloadable GeoTIFF.",
      {"layer": STR("LULC raster"), "metric": S("string", "Metric", enum=["SHDI", "SIDI", "PR", "ED", "PLAND"]), "window_m": S("number", "Window side in metres"),
       "class_code": S("integer", "Class for PLAND"), "output_name": STR("Output file name")}, ["layer", "metric", "window_m", "output_name"])
def _mw(ctx, layer, metric, window_m, output_name, class_code=None):
    return patternops.moving_window_raster(ctx.store, layer, metric, window_m, output_name, class_code)


@tool("hotspot_analysis", "Spatial hotspots on a block-aggregated grid: global Moran's I, Getis-Ord Gi* (90/95/99% hot/cold, optional FDR) and Local Moran's I "
      "clusters (HH, LL, HL, LH). Variable: 'change', 'gain' or 'loss' of a class between layer and second_layer, 'presence' (share of a class), or "
      "'value' of a continuous raster. Writes GeoTIFFs and returns the strongest hot/cold spots with coordinates.",
      {"layer": STR("Raster (earlier map for change variables)"), "variable": S("string", "Variable", enum=["change", "gain", "loss", "presence", "value"]),
       "second_layer": STR("Later map for change/gain/loss"), "class_code": S("integer", "Class for gain/loss/presence"),
       "block": S("integer", "Aggregation block in cells per side (default 10)"), "radius": S("integer", "Neighbour radius in blocks (default 1)"),
       "kernel_shape": S("string", "square or circle", enum=["square", "circle"]), "method": S("string", "gi, lisa or both", enum=["gi", "lisa", "both"]),
       "fdr": S("boolean", "Benjamini-Hochberg FDR correction (default true)"), "permutations": S("integer", "LISA permutations (default 199)"),
       "output_prefix": STR("Prefix for output files")}, ["layer"])
def _hs(ctx, layer, variable="value", second_layer=None, class_code=None, block=10, radius=1, kernel_shape="square", method="both", fdr=True,
        permutations=199, output_prefix="hotspot"):
    return patternops.hotspot_analysis(ctx.store, layer, variable, second_layer, class_code, block, radius, kernel_shape, method, fdr,
                                       permutations, output_prefix)


# ---------------- v0.8.0: spectral indices and classification ----------------
BANDMAP = S("object", "Band roles -> raster, e.g. {\"red\": \"s2.tif#3\", \"nir\": \"s2.tif#7\"}. Roles: " + ", ".join(classify.ROLES) +
            ". Use 'file.tif#k' for band k of a multi-band file, or a single-band file name.")
PRESET = S("string", "Sensor preset that fills band_map from a multi-band 'stack'", enum=list(classify.PRESETS))
INDEX_LIST = S("array", "Spectral indices: " + ", ".join(classify.INDICES), items={"type": "string"})


def _register(ctx, *names):
    for n in names:
        if n and n in ctx.store.outputs:
            ctx.store.add(n, ctx.store.outputs[n])  # make generated maps selectable as session layers


def _bands(ctx, band_map, stack, preset, scale, offset):
    s0, o0 = (1.0, 0.0)
    if stack and preset:
        bm, s0, o0 = classify.preset_band_map(ctx.store, stack, preset)
        band_map = {**bm, **(band_map or {})}
    return band_map or {}, (s0 if scale is None else scale), (o0 if offset is None else offset)


@tool("spectral_indices", "Compute spectral index GeoTIFFs (" + ", ".join(classify.INDICES) + ") from mapped bands with reflectance scaling; outputs become session layers.",
      {"band_map": BANDMAP, "stack": STR("Multi-band file (with preset)"), "preset": PRESET, "indices": INDEX_LIST,
       "scale": S("number", "Reflectance = DN*scale+offset"), "offset": S("number", "Offset"), "prefix": STR("Output name prefix")}, ["indices"])
def _si(ctx, indices, band_map=None, stack=None, preset=None, scale=None, offset=None, prefix=""):
    bm, sc, of = _bands(ctx, band_map, stack, preset, scale, offset)
    res = classify.compute_index_rasters(ctx.store, bm, indices, sc, of, prefix)
    _register(ctx, *[r["output"] for r in res["indices"]])
    return res


@tool("classify_image", "Supervised LULC classification: samples features (bands, indices, texture, extra layers) at training points, cross-validates with random "
      "AND spatial-block k-fold, reports accuracy, per-class F1 and permutation importance, then maps the whole image with a confidence raster. The map becomes a "
      "session layer usable by the accuracy, change and landscape tools.",
      {"table": STR("Training table"), "class_column": STR("Integer class column"), "x_column": STR("X/lon"), "y_column": STR("Y/lat"),
       "epsg": S("integer", "EPSG of points if different from image"), "band_map": BANDMAP, "stack": STR("Multi-band file (with preset)"), "preset": PRESET,
       "extra_layers": S("array", "Extra single-band layers (DEM, SAR)", items={"type": "string"}), "indices": INDEX_LIST,
       "texture": S("boolean", "Add 5x5 standard deviation texture"), "scale": S("number", "Reflectance scale"), "offset": S("number", "Reflectance offset"),
       "model": S("string", "Classifier", enum=classify.MODELS), "n_trees": S("integer", "Trees / iterations (default 150)"),
       "block_m": S("number", "Spatial CV block size in metres (default 1000)"), "folds": S("integer", "CV folds (default 5)"),
       "smooth": S("integer", "Majority filter window 0/3/5/7"), "output_name": STR("Output map name"), "labels": S("object", "Optional {code: name}"),
       "predict": S("boolean", "Map the whole image (default true)")},
      ["table", "class_column", "x_column", "y_column"])
def _cl(ctx, table, class_column, x_column, y_column, epsg=None, band_map=None, stack=None, preset=None, extra_layers=(), indices=("NDVI",), texture=False,
        scale=None, offset=None, model="Random Forest", n_trees=150, block_m=1000.0, folds=5, smooth=0, output_name="classified.tif", labels=None, predict=True):
    if table not in ctx.tables:
        raise ValueError(f"Table not loaded: {table}")
    bm, sc, of = _bands(ctx, band_map, stack, preset, scale, offset)
    res = classify.train_and_predict(ctx.store, ctx.__dict__.setdefault("models", {}), ctx.tables[table], class_column, x_column, y_column,
                                     band_map=bm, extra_layers=list(extra_layers or ()), indices=list(indices or ()), texture=texture, scale=sc,
                                     offset=of, model=model, n_trees=n_trees, block_m=block_m, folds=folds, epsg=epsg, predict=predict,
                                     output_name=output_name, smooth=smooth, labels=labels)
    if res.get("prediction"):
        _register(ctx, res["prediction"]["output"], res["prediction"].get("confidence_output"))
    return res


@tool("cluster_image", "Unsupervised K-means clustering of the feature stack (exploration only; clusters must be labelled by the user).",
      {"band_map": BANDMAP, "stack": STR("Multi-band file (with preset)"), "preset": PRESET, "extra_layers": S("array", "Extra layers", items={"type": "string"}),
       "indices": INDEX_LIST, "texture": S("boolean", "Add texture"), "scale": S("number", "Scale"), "offset": S("number", "Offset"),
       "k": S("integer", "Number of clusters"), "output_name": STR("Output name")}, ["k"])
def _km(ctx, k, band_map=None, stack=None, preset=None, extra_layers=(), indices=(), texture=False, scale=None, offset=None, output_name="kmeans_clusters.tif"):
    bm, sc, of = _bands(ctx, band_map, stack, preset, scale, offset)
    spec = classify.build_spec(ctx.store, bm, list(extra_layers or ()), list(indices or ()), texture, sc, of)
    res = classify.kmeans(ctx.store, spec, k, output_name)
    _register(ctx, output_name)
    return res


# ---------------- v0.9.0: drivers, scenario simulation, hindcast validation ----------------
DRIVERS = S("array", "Drivers: objects {type: distance_to_class, class: code} | {type: distance_to_layer, name: raster} | {type: slope, name: dem} | "
            "{type: layer, name: raster}. Default: distance to each target class.", items={"type": "object"})


@tool("driver_analysis", "Screen candidate drivers of land change for the main transitions between two maps: Cramér's V and AUC per driver and transition, VIF and correlations.",
      {"map_from": STR("Earlier LULC map"), "map_to": STR("Later LULC map"), "drivers": DRIVERS, "n_transitions": S("integer", "Number of transitions (default 6)")},
      ["map_from", "map_to"])
def _da(ctx, map_from, map_to, drivers=None, n_transitions=6):
    return simulate.driver_analysis(ctx.store, map_from, map_to, drivers, n_transitions)


@tool("make_driver_layers", "Write driver GeoTIFFs (distance to classes or features in metres, slope in degrees) that can also be used as MOLUSCE factors.",
      {"base_map": STR("LULC map for class distances"), "classes": S("array", "Class codes", items={"type": "integer"}),
       "layers": S("array", "Feature rasters (roads, rivers): distance to non-zero cells", items={"type": "string"}), "dem": STR("DEM for slope")}, ["base_map"])
def _mdl(ctx, base_map, classes=(), layers=(), dem=None):
    res = simulate.make_driver_layers(ctx.store, base_map, classes or (), layers or (), dem)
    _register(ctx, *res["outputs"])
    return res


@tool("simulate_lulc", "Markov-CA land-change simulation: calibrates transition potentials (logistic, Random Forest or ANN) and Markov quantities on map_from->map_to, "
      "allocates change with a cellular automaton under a scenario (Business as usual, Ecological protection, Development priority; protected mask, forbidden "
      "transitions, demand multipliers) and, if validate_against is given, validates the result (FoM, Kappa simulation, null model, other simulated maps such as MOLUSCE).",
      {"map_from": STR("Calibration earlier map"), "map_to": STR("Calibration later map"), "year_from": S("integer", "Year of map_from"),
       "year_to": S("integer", "Year of map_to"), "year_target": S("integer", "Year to simulate"), "start_map": STR("Map to start from (default map_to)"),
       "start_year": S("integer", "Year of start_map (default year_to)"), "drivers": DRIVERS, "model": S("string", "Potential model", enum=simulate.POTENTIAL_MODELS),
       "n_transitions": S("integer", "Transitions to model (default 6)"), "scenario": S("string", "Scenario", enum=list(simulate.SCENARIOS)),
       "growth_classes": S("array", "Development classes", items={"type": "integer"}), "natural_classes": S("array", "Natural classes", items={"type": "integer"}),
       "multipliers": S("object", "{'i->j': factor}"), "forbidden": S("array", "Forbidden transitions 'i->j'", items={"type": "string"}),
       "protected_layer": STR("Protected-area raster (non-zero = no change)"), "apply_protection": S("boolean", "Force protection on/off (default: scenario)"),
       "neighbourhood": S("integer", "3, 5 or 7"), "weight": S("number", "Neighbourhood weight 0-1 (default 0.5)"), "iterations": S("integer", "CA iterations"),
       "stochastic": S("number", "Random perturbation 0-1"), "output_name": STR("Output map name"), "potential_prefix": STR("Save potential maps with this prefix"),
       "validate_against": STR("Observed map of the target year (hindcast)"), "compare_with": S("array", "Other simulated maps to compare", items={"type": "string"})},
      ["map_from", "map_to", "year_from", "year_to", "year_target"])
def _sim(ctx, map_from, map_to, year_from, year_to, year_target, validate_against=None, compare_with=(), **kw):
    sim = simulate.simulate(ctx.store, map_from, map_to, year_from, year_to, year_target, **kw)
    _register(ctx, sim["output"], *sim.get("potential_maps", []))
    out = dict(simulation=sim)
    if validate_against:
        out["validation"] = simulate.validate(ctx.store, sim["start_map"], validate_against, [sim["output"]] + list(compare_with or ()))
    return out


@tool("validate_simulation", "Compare one or more simulated maps (yours or MOLUSCE output) with the observed map: FoM, hits/misses/false alarms, Kappa simulation, "
      "quantity/allocation disagreement, versus the null (no-change) model.",
      {"initial": STR("Map at the start of the simulation"), "observed": STR("Observed map of the target year"),
       "simulated": S("array", "Simulated maps", items={"type": "string"})}, ["initial", "observed", "simulated"])
def _vs(ctx, initial, observed, simulated):
    return simulate.validate(ctx.store, initial, observed, simulated)


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
