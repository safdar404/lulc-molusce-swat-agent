<p align="center"><img src="logo.svg" width="140" alt="LULC Agent logo"/></p>

# LULC - MOLUSCE - SWAT+ Research Agent

Open-source tools for a land-use/land-cover (LULC) change, MOLUSCE simulation and SWAT+ hydrology PhD workflow:

- **Streamlit web app** (`app.py`): upload GeoTIFFs and CSVs, run audited checks and statistics, ask an AI agent that uses the same tools, download a processing log.
- **Live map canvas** (`canvas_tab.py`, `live.py`, `cartography.py`): real-time processing monitor that computes LULC, change, disagreement, spectral-index, RGB-composite and continuous maps strip by strip while drawing them on a canvas, then composes an export-ready map with title, legend, scale bar, north arrow, grid coordinates and metadata box (PNG up to 600 DPI, PDF).
- **Advanced accuracy & change analysis** (`olofsson.py`, `intensity.py`, `changeops.py`, `advanced_tabs.py`): Olofsson et al. (2014) area-adjusted accuracy with error-adjusted areas and 95% CIs, sample design and stratified random points, multi-date Intensity Analysis (Aldwaik & Pontius 2012), change-frequency and trajectory maps.
- **Landscape pattern & hotspots** (`landscape.py`, `hotspot.py`, `patternops.py`, `pattern_tab.py`): FRAGSTATS-definition class and landscape metrics across dates, moving-window maps, Getis-Ord Gi* and Local Moran's I hotspot maps with FDR correction.
- **Look and feel** (`ui.py`, `logo.svg`, `logo.png`): vibrant multi-colour theme, logo, hero header, colour-coded metric cards and charts.
- **Analysis core** (`metrics.py`, `rasterops.py`, `hydro.py`, `knowledge.py`, `store.py`, `session.py`, `agent_tools.py`, `agent.py`): statistics, raster operations and the agent loop.

## Repository layout
All files sit in the repository root (flat layout), so the whole project can be uploaded through the GitHub web page.
Modules use plain absolute imports (`import metrics`), so do **not** add an `__init__.py` to the root.

## What it does
MOLUSCE geometry checklist (CRS, cell size, rows/columns, origin, NoData), LULC area statistics (ha), from-to transition matrices,
accuracy assessment from validation points (overall, user's and producer's accuracy, kappa), hindcast validation
(kappa, quantity/allocation disagreement, figure of merit), good-practice area-adjusted accuracy (Olofsson 2014) with error-adjusted
areas, Pontius quantity/allocation/exchange/shift, accuracy sample design, multi-date Intensity Analysis (interval, category, transition levels,
stationarity, gain/loss/net/swap, alternation), change-frequency and trajectory rasters, landscape metrics (fragmentation, aggregation, diversity) and
moving-window maps, Gi* / LISA hotspot analysis, NDVI/NDWI/NDBI, NSE/PBIAS/R2/KGE, a 30-practical teaching guide, and an audit log
in the manual's template (date, input, tool version, parameters, output, note).

## What it does not do
It does **not** run MOLUSCE's ANN or cellular automata, QSWAT+ delineation, image classification or SWAT+ calibration. It prepares inputs,
checks them and evaluates results. AI output can be wrong: verify every number independently before it enters a thesis.

## Quick start
```
pip install -r requirements.txt
streamlit run app.py
```
Set `ANTHROPIC_API_KEY` (environment variable or `.streamlit/secrets.toml`) to use the Agent tab; the model name is editable in the sidebar.
On Streamlit Community Cloud set **Main file path** to `app.py`. With Docker: `docker build -t lulc-agent . && docker run -p 8501:8501 lulc-agent`.
Only add `ANTHROPIC_API_KEY` to a public deployment's secrets if you accept that visitors spend your credit.

## Testing status
`pytest -q` runs `test_core.py`, `test_advanced.py` and `test_pattern.py` (Olofsson 2014 worked-example benchmark, hand-computed intensity analysis,
store-level accuracy / intensity / trajectory pipelines; hand-computed landscape metrics, brute-force Gi*). Landscape metrics were
cross-checked against pylandstats and hotspot statistics against PySAL esda. `test_core.py` covers confusion matrix, accuracy and kappa, Pontius disagreement, figure of merit, hydrology metrics, raster area/transition
statistics on a synthetic in-memory GeoTIFF, and the tool registry. The agent loop has not been tested against the live API.
Treat this as research software (v0.2, experimental).

## Data and privacy
Uploads stay in session memory. The agent sends tool results (not rasters) to the model provider. See [SECURITY.md](SECURITY.md).

## Acknowledgement
Workflow follows the "PhD Research & Teaching Manual: LULC Change Detection, MOLUSCE Land-Use Simulation & SWAT/SWAT+ Hydrological Modelling in QGIS".
MOLUSCE is a NextGIS plugin; QGIS and SWAT+ belong to their respective projects. This project is not affiliated with them.

## Licence
MIT (see LICENSE).
