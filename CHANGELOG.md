# Changelog
## 1.4.5
- **Background jobs for composites** (`jobs.py`): the download runs in its own thread kept in the session, and the page polls its
  progress every 3 s. Before, a rerun (which Streamlit triggers when the browser's websocket reconnects: a sleeping laptop, a slow link,
  a throttled background tab) cancelled the 10-minute Astore composite in progress.

## 1.4.4
- **Gap fill for persistently flagged pixels** (on by default): pixels that the cloud mask rejected in EVERY scene but that were observed
  take the median of all valid observations, reported separately as "gap-filled" (observation count 0). With the 1.4.3 rule alone the
  Astore composite stayed at 81.4 %: above ~5 000 m the 1.38 um cirrus band sees the ground, so Fmask flags glacier ice as cirrus/cloud
  in every scene, while real clouds move between acquisitions.
- **Mask diagnostics**: each composite reports why pixels were rejected (high-confidence cloud, cirrus, shadow, other flags).
- Agent tool `download_composite` gains `fill_gaps`; the report states the clear and gap-filled shares.

## 1.4.3
- Landsat snow-aware mask keeps pixels with HIGH snow/ice confidence (QA_PIXEL bits 12-13) even when Fmask also flags them as
  high-confidence cloud. In the live Astore run the composite reached 81 % coverage and the remaining holes were exactly the glaciers,
  which Fmask labelled cloud in every scene.

## 1.4.2
- Imagery: hard memory caps for basin-wide composites (GDAL block cache 96 MB, 4 MB VSI cache per file, 16 MB warp buffer, freed after each band).
  GDAL's default cache is 5 % of the host's RAM, which could get the cloud app restarted mid-download when a dozen full Landsat scenes were open.

## 1.4.1
Fixes found in the live Astore basin run (3,988 km², Landsat 8/9, Aug-Sep 2025):
- **Scene selection per footprint tile**: the composite took the least-cloudy scenes overall, which all came from one Landsat row, so the
  southern basin had no data (37 % coverage). Scenes are now chosen per path/row (Landsat) or MGRS tile (Sentinel-2).
- **Snow-aware Landsat cloud mask**: only high-confidence cloud, cloud shadow and high-confidence cirrus are rejected; dilated-cloud buffers
  and medium-confidence cloud, which Fmask often assigns to bright snow and glacier ice, are kept. Snow-flagged pixels are kept unless the
  cloud confidence is high. A "strict" option restores the old behaviour.
- **Memory-safe compositing**: masks are bit-packed and bands are composited in row strips, so many scenes over a whole basin fit in memory.
- Coverage warning when less than 90 % of the area has a clear observation; the scene list shows the footprint tiles.
- Hypsometry chart redrawn as band bars plus cumulative curve (it showed thin bars and a negative axis).
## 1.4.0
- New **🏔️ Snow, ice & elevation** tab (`cryo.py`, `cryo_tab.py`) for mountain basins such as Astore and Hunza.
  - **Hypsometry**: area per elevation band or custom zones (e.g. 2500 / 3500 / 4500 / 5500 m), cumulative hypsometric curve,
    elevation range, mean, median, 5-95 % range and hypsometric integral, clipped to the basin polygon.
  - **Snow and ice mapping** from a composite: NDSI > 0.4 and NIR > 0.11 (Hall et al. 1995), optional WorldCover water mask; snow / ice
    map and NDSI raster.
  - **Elevation-zone statistics** for any class map (snow, glaciers, land cover): area and share per zone, and the 50 % snowline.
- **Basin support**: KMZ / KML upload, including ArcGIS "Layer To KML" exports, whose HTML attribute tables are turned back into columns
  (e.g. GADM district names). Downloads can use a vector's extent and be **clipped to the basin polygon**. Pixel limit raised to 9
  million per band (about 90 × 90 km at 30 m).
- NDSI added to the spectral index library.
- Agent: new tools `hypsometry`, `map_snow_cover`, `elevation_zone_statistics`; download tools accept `vector` and `clip_vector`.
  The report gains a "Basin topography, snow and ice" section.
## 1.3.1
- Verified live on Streamlit Cloud (Islamabad, 10 × 10 km): Sentinel-2 L2A 2025 search (46 scenes), 6-scene cloud-free composite
  (1021 × 1023 px at 10 m, 100 % coverage), Copernicus DEM (491-776 m) and ESA WorldCover 2021 on the composite's grid.
- Fix: points generated in the Area-adjusted accuracy tab now appear immediately in earlier tabs (e.g. as training data in
  Classification) instead of after the next click.
- Map pickers (area-adjusted accuracy, intensity analysis, landscape metrics, SWAT+ link) now default to categorical land-cover maps
  and skip multi-band composites and auxiliary rasters (observation counts, confidence, hotspot outputs).
- Classification: the class-column guess skips empty columns, so generated points use `map_class` rather than the blank `reference_class`.
## 1.3.0
- New **🌍 Download imagery** tab (`imagery.py`, `imagery_tab.py`) using the Microsoft Planetary Computer STAC API (no account needed).
  - **Area of interest**: a centre point plus size, a lon/lat bounding box, the extent of a loaded vector, or the exact grid of a loaded
    raster, so every download lines up pixel for pixel with your maps.
  - **Cloud-free composites** from Sentinel-2 L2A (10 bands, 10 m, from 2017) or Landsat 4/5/7/8/9 Collection 2 Level-2 (6 bands, 30 m,
    from 1984). Scene search with cloud limit and a scene table; per-pixel masking of clouds, shadows and cirrus (Sentinel-2 SCL,
    Landsat QA_PIXEL); conversion to surface reflectance, including the -1000 DN offset of Sentinel-2 processing baseline 04.00+;
    median or mean composite; observation-count raster; true-colour preview. Only the area of interest is read from the files.
  - Composites are stored as reflectance × 10 000 with band names, and plug straight into the Classification tab (new preset for the
    6-band Landsat composite).
  - **Copernicus DEM GLO-30** and **ESA WorldCover** (2020 / 2021, with class names) on the same grid.
  - Memory guard: at most 4 million pixels per band (about 20 × 20 km at 10 m or 60 × 60 km at 30 m).
- Agent: new tools `search_scenes`, `download_composite`, `download_dem`, `download_worldcover`. The report gains a Data acquisition section.
## 1.2.0
- **Report generator** (`report.py`, `report_tab.py`, in the renamed **📝 Log & report** tab, plus an agent tool `generate_report`).
  - Every analysis result is now kept in the session (not only the short log line), and the report is written from it: a methods and
    results narrative containing the numbers that were actually computed, numbered tables, finished maps (title, legend with areas,
    scale bar, north arrow, grid, metadata) and charts, a Limitations section, an alphabetical reference list limited to the methods
    used, and the processing log as an appendix.
  - Covers classification, area-adjusted accuracy, transitions, intensity analysis, trajectories, landscape metrics, hotspots, drivers,
    Markov-CA simulation and hindcast validation, SWAT+ lookup, Curve Number runoff, RUSLE, streamflow evaluation, LULC flow
    attribution and zonal statistics. Choose which analyses to include; by default the latest run of each.
  - Downloads: editable Word (.docx) and a self-contained, print-ready HTML file (open it and print to PDF).
  - Class names given anywhere in the session label every map. Gi* and LISA maps use diverging hot / cold colours (also in the map composer).
- Single version source `app_version.py`. New dependency: `python-docx`.
## 1.1.0
- **Vector support** (`vectorops.py`, `vector_tab.py`, new **🧭 Vector tools** tab and a sidebar uploader).
  - Reads zipped shapefiles (any folder depth), shapefile parts uploaded together, GeoPackage, GeoJSON, KML and FlatGeobuf. Invalid
    geometries are repaired. Every operation reprojects to the raster CRS, so WGS84 vectors work with UTM rasters.
  - **Describe and preview** a layer over any raster, with its attribute table.
  - **Rasterize** a numeric field, a text field (coded 1..n, lookup returned) or a constant onto any raster grid, with an all-touched
    option for lines. Use the output for roads and rivers as distance drivers, protected-area masks, hydrologic soil groups or zones.
  - **Training samples from polygons**: pixel centres per class with a polygon ID; **points → table** for GPS validation points.
  - **Zonal statistics**: class area and % per polygon with the majority class (categorical), or mean / std / min / max / median
    (continuous), e.g. LULC composition of SWAT+ sub-basins or districts.
  - **Polygonize** any categorical raster (classified map, hotspot clusters, change map) and download it as GeoPackage or GeoJSON.
- Classification: when the training table has a `polygon_id` column, the classifier also reports **polygon-grouped
  cross-validation**, so pixels of one polygon are never split between training and testing.
- SWAT+ link tab: map selection now defaults to categorical rasters.
- Agent: new tools `describe_vector`, `rasterize_vector`, `vector_training_samples`, `vector_points_to_table`, `zonal_statistics`,
  `polygonize_raster`; `list_session` reports vector layers.
- New dependencies: `geopandas`, `pyogrio`.
## 1.0.0
- New **🌊 SWAT+ link** tab (`swatlink.py`, `swat_tab.py`), which closes the workflow from imagery to hydrology.
  - **LULC → SWAT+ codes**: editable class table with codes suggested from class names, a QSWAT+ landuse lookup CSV
    (`LANDUSE_ID,SWAT_CODE`) and area per SWAT+ code for every map or scenario.
  - **Curve Number runoff** per scenario: CN from SWAT+ code and hydrologic soil group (raster or uniform), SWAT slope adjustment of
    CN2 (Williams 1995), Ia = 0.2 S or 0.05 S (Hawkins et al. 2002), design storm and daily rainfall series, CN and runoff GeoTIFFs,
    change versus the baseline map. Editable TR-55 Curve Number table.
  - **RUSLE erosion** per scenario: R, K, P as constants or rasters, LS from a DEM with a fixed slope length or D8 flow accumulation,
    C from the SWAT+ code (editable), severity classes, soil loss by land use and soil-loss GeoTIFFs.
  - **Streamflow evaluation**: NSE, KGE, R², PBIAS and RSR with Moriasi et al. (2007, 2015) ratings, Yilmaz et al. (2008) flow-duration
    signatures (FHV, FLV, FMS), warm-up removal, calibration / validation split, daily / monthly / annual aggregation and an FDC chart.
  - **LULC impact between two SWAT+ runs** (same climate and parameters): change in mean, high (Q5), median and low (Q95) flow, and FDCs.
- Agent: new tools `swat_landuse_lookup`, `curve_number_runoff`, `rusle_erosion`, `flow_evaluation`, `lulc_flow_attribution`.
- Header updated to show the full workflow.
## 0.9.0
- New **🔮 Drivers & scenarios** tab (`simulate.py`, `simulate_tab.py`).
  - **Driver layers**: distance to a class (recomputed from each base map), distance to features such as roads or rivers, slope from a
    DEM (Horn 1981) and any continuous layer. Exportable as GeoTIFFs for use as MOLUSCE factors.
  - **Driver screening** per transition: Cramér's V and AUC heat maps, variance inflation factors and a correlation matrix.
  - **Transition potentials** with logistic regression, Random Forest or an ANN (multilayer perceptron, as in MOLUSCE), trained on
    balanced samples with a hold-out AUC.
  - **Markov quantities** with fractional matrix powers for any projection length, and **cellular-automaton allocation** with a
    neighbourhood effect, iterations and optional stochastic perturbation.
  - **Scenarios**: business as usual, ecological protection and development priority (development / natural classes, protected-area
    mask, forbidden transitions, demand multipliers), with a one-click three-scenario comparison chart.
  - **Hindcast validation**: figure of merit with hits / misses / wrong hits / false alarms, Kappa simulation (van Vliet et al. 2011),
    quantity / allocation disagreement and producer's / user's accuracy of change, against the null (no-change) model and any other
    simulated map, e.g. your MOLUSCE output.
- Agent: new tools `driver_analysis`, `make_driver_layers`, `simulate_lulc`, `validate_simulation`, and a rule to hindcast before projecting.
## 0.8.0
- New **🛰️ Classification** tab (`classify.py`, `classify_tab.py`): the app now produces LULC maps, not only evaluates them.
  - **Multi-band GeoTIFFs** are read in full; each band is addressable as `file.tif#k` in every tool and tab (e.g. RGB composites from a stack).
  - **Sensor presets** with band order and reflectance scaling: Sentinel-2 L2A (10 or 4 bands), Landsat 8/9 and 4/5/7 Collection 2 L2, or custom.
  - **15 spectral indices** with references: NDVI, EVI, SAVI, MSAVI, GNDVI, NDWI, MNDWI, AWEIsh, NDMI, NBR, NDBI, UI, BSI, NDRE, CIre.
    Index maps are written as GeoTIFFs and added to the session layers.
  - **Feature stacks**: bands + indices + 5×5 texture + extra layers (DEM, slope, SAR).
  - **Classifiers**: Random Forest, Extra Trees, histogram gradient boosting (XGBoost-style), SVM (RBF), Gaussian maximum likelihood,
    plus K-means clustering. Class-balanced weighting.
  - **Validation**: random stratified k-fold *and* spatial block k-fold side by side, with the optimism gap, per-class producer's / user's
    accuracy and F1, confusion matrix and permutation feature importance. Duplicate points in one pixel are removed.
  - **Mapping** in row chunks (memory-safe), a confidence raster (max class probability), optional majority filter, class areas.
    Maps are added to the session layers so they flow into Accuracy, Area-adjusted accuracy, Intensity, Landscape and the Live canvas.
- Agent: new tools `spectral_indices`, `classify_image`, `cluster_image`; `inspect_raster` reports band count.
- New dependency: `scikit-learn`.
## 0.7.0
- New **🧩 Landscape & hotspots** tab.
- **Landscape metrics** (`landscape.py`) with FRAGSTATS definitions, for one or several dates. Class level: CA, PLAND, NP, PD, LPI, TE, ED,
  LSI, AREA_MN / AM / CV, SHAPE_MN / AM, FRAC_MN, ENN_MN, TCA, CPLAND, AI, COHESION, DIVISION, MESH, SPLIT. Landscape level adds CONTAG,
  SHDI, SHEI, SIDI, SIEI, PR, PRD. 8- or 4-neighbour patch rule, edge depth for core area, largest-patch list, first-to-last change,
  grouped bar charts and Excel export. Cross-checked against pylandstats 3.1: identical values for every shared metric (SHDI and CONTAG
  follow FRAGSTATS' cell-proportion definition, which pylandstats approximates from adjacencies).
- **Moving-window maps**: SHDI, SIDI, patch richness, edge density or a class's PLAND in a square window, as a GeoTIFF with preview.
- **Hotspot analysis** (`hotspot.py`): global Moran's I, Getis-Ord Gi* with 90/95/99 % hot/cold bins and optional Benjamini-Hochberg
  FDR correction, and Local Moran's I (LISA) clusters by conditional permutation. Works on LULC change, gain or loss of a class, class
  share, or any continuous raster, aggregated to blocks; returns the strongest hot and cold spots with coordinates. Gi*, global Moran's I
  and local Moran's I values are identical to PySAL esda 2.10.
- Agent: new tools `landscape_metrics`, `moving_window_map`, `hotspot_analysis`, and a rule to report scale settings for hotspots.
- New dependency: `scipy`.
## 0.6.0
- New **📏 Area-adjusted accuracy** tab (`olofsson.py`): Olofsson et al. (2014) good-practice estimators. Area-weighted error matrix,
  overall / user's / producer's accuracy with 95% CI, error-adjusted class areas with 95% CI (chart shows where pixel counts are biased),
  quantity / allocation disagreement (Pontius & Millones 2011) split into exchange and shift (Pontius & Santacruz 2014), F1 per class,
  ready-to-paste methods paragraph and Excel export. Works from a raster + validation CSV or from a published error matrix.
  Validated against the paper's worked example (OA 94.7 ± 1.8 %, deforestation 21,158 ± 6,158 ha).
- **Sample design**: total sample size for a target SE (Olofsson Eq. 13), four allocation rules, and stratified random point
  generation saved as a session table with a blind interpretation sheet.
- New **📈 Intensity analysis** tab (`intensity.py`): Aldwaik & Pontius (2012) interval (fast/slow), category (active/dormant
  gain and loss) and transition (targeted/avoided) levels for any number of dates, stationarity across intervals, gross gain / loss /
  net / swap and alternation (Pontius et al. 2017), with charts, transition matrices, methods text and Excel export.
- New change maps (`changeops.py`): change-frequency raster and per-category trajectory raster (stable, gain/loss with or without
  alternation) with areas. Class areas are exact for projected rasters and spherical for lat/lon rasters.
- Agent: six new tools (`area_adjusted_accuracy`, `design_accuracy_sample`, `generate_sample_points`, `intensity_analysis`,
  `change_frequency_raster`, `trajectory_raster`) and rules to report error-adjusted areas and run intensity analysis after accuracy checks.
- Fix: the app crashed (duplicate element key) once an output GeoTIFF existed and 2+ rasters were loaded, because the same download
  buttons were drawn in several tabs.
## 0.5.0
- New **🛰️ Live map canvas** tab. A real-time processing monitor runs the analysis strip by strip at full resolution and draws
  the result on a canvas as it is computed, with a progress bar, live metrics, running class areas and a console log.
  Analyses: classified LULC map, NDVI / NDWI / NDBI, LULC change (from → to), hindcast disagreement, satellite RGB composite
  (true / false colour, 2–98 % stretch) and continuous rasters (DEM, single band).
- New export-ready **map composer** (`cartography.py`): title and subtitle, map frame with grid coordinates (metres or degrees),
  legend (class colours with hectares and %, or a colour bar with statistics), alternating scale bar, north arrow, metadata box
  (CRS, pixel size, source, author, date) and neatline. Download as PNG (150–600 DPI) or print PDF. Any loaded raster or
  generated output can be mapped.
- Generated outputs (index, transition, disagreement GeoTIFFs) can now be used as inputs to other tools.
## 0.4.2
- Fix: after a multi-file update Streamlit Cloud kept old helper modules cached ("cannot import name 'friendly_error' from 'agent'").
  `app.py` now reloads any local module whose file changed, so updates apply without a manual reboot.
## 0.4.1
- Fix: the page could freeze the browser tab (and drop the connection, showing "Oh no. Error running app"). The always-on floating
  logo animation forced constant redraws of the filtered SVG, halving the frame rate. The logo now moves only on hover, uses a
  10 KB pre-rendered PNG (`logo_small.png`), and page-wide perspective, fixed backgrounds and backdrop blur were removed. Idle cost is now zero.
- Agent: API failures (no credit, bad key, unknown model, rate limit, outage) show a plain explanation instead of raw JSON, the failed
  question no longer corrupts the conversation, and a built-in analysis of the loaded data is shown instead.
- New "Quick analysis" button and offline mode without an API key; new `describe_table` tool for any CSV.
- Guide tab: the MOLUSCE / QSWAT+ note is rewritten as a workflow tip.
## 0.4.0
- Logo: added a small AI-agent robot head and a 3D look (extruded hexagon badge, glossy face, shaded globe, drop shadows).
- 3D interface: tilted hero slab with a perspective grid and floating logo, extruded push-down buttons, raised tab pills in a recessed tray,
  glossy metric tiles with coloured edges that tilt on hover, 3D section icons and workflow chips, lifted data panels.
  Motion is disabled for users who prefer reduced motion.
## 0.3.0
- New AI-agent logo (`logo.svg`, `logo.png`) used as page icon, header, sidebar brand and agent chat avatar.
- Redesigned Streamlit frontend (`ui.py`): vibrant violet-pink-orange-teal palette, gradient hero, pill tabs, colour-coded metric cards,
  palette bar chart, practical cards, workflow strip, dark gradient sidebar with session counters. Works in light and dark themes.
- Hydrology tab now pre-selects distinct observed/simulated columns; tiny negative disagreement values no longer show as "-0.000".
## 0.2.1
- Fix: the app could not start. Files had been uploaded flat but still used package-relative imports (`from . import ...`) and `app.py`
  looked for `src/lulc_core`. Switched every module to absolute imports, removed the root `__init__.py`, and pointed `pyproject.toml`
  and the `Dockerfile` at the flat layout (`streamlit run app.py`).
- Added `test_core.py` (the tests the README described were not in the repository); README no longer links missing folders and docs.
## 0.2.0
- Shared `lulc_core` package; Streamlit web app (rasters and tables in memory, audited tools, agent chat, processing log).
- QGIS plugin refactored to share tested metrics and knowledge files.
- Tests: statistics, raster operations on synthetic GeoTIFFs, app smoke test. CI on Python 3.10-3.12.
## 0.1.0
- First QGIS plugin prototype.
