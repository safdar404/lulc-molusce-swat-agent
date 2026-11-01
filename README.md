# LULC - MOLUSCE - SWAT+ Research Agent

Open-source tools for a land-use/land-cover (LULC) change, MOLUSCE simulation and SWAT+ hydrology PhD workflow:

- **Streamlit web app** (`streamlit_app/`): upload GeoTIFFs and CSVs, run audited checks and statistics, ask an AI agent that uses the same tools, download a processing log.
- **QGIS plugin** (`qgis_plugin/lulc_agent/`): the same idea as a chat panel inside QGIS, with approval-gated write tools.
- **Shared core** (`src/lulc_core/`): tested statistics and raster operations.

## What it does
MOLUSCE geometry checklist (CRS, cell size, rows/columns, origin, NoData), LULC area statistics (ha), from-to transition matrices,
accuracy assessment from validation points (overall, user's and producer's accuracy, kappa), hindcast validation
(kappa, quantity/allocation disagreement, figure of merit), NDVI/NDWI/NDBI, NSE/PBIAS/R2/KGE, a 30-practical teaching guide, and an audit log
in the manual's template (date, input, tool version, parameters, output, note).

## What it does not do
It does **not** run MOLUSCE's ANN or cellular automata, QSWAT+ delineation, image classification or SWAT+ calibration. It prepares inputs,
checks them and evaluates results. AI output can be wrong: verify every number independently before it enters a thesis.

## Quick start
```
pip install -r requirements.txt
streamlit run streamlit_app/app.py
```
Set `ANTHROPIC_API_KEY` (environment variable or `.streamlit/secrets.toml`) to use the Agent tab; the model name is editable in the sidebar.
Publishing steps: see [docs/DEPLOY.md](docs/DEPLOY.md). Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Testing status
`pytest` covers the statistics (including the manual's confusion-matrix example: OA 0.89, kappa 0.853), raster operations on synthetic GeoTIFFs, hydrology
metrics, the tool registry and an app smoke test. The QGIS plugin sources compile in CI but are **not yet tested inside a live QGIS session**.
The agent loop has not been tested against the live API in CI. Treat this as research software (v0.2, experimental).

## Data and privacy
Uploads stay in session memory. The agent sends tool results (not rasters) to the model provider. See [SECURITY.md](SECURITY.md).

## Acknowledgement
Workflow follows the "PhD Research & Teaching Manual: LULC Change Detection, MOLUSCE Land-Use Simulation & SWAT/SWAT+ Hydrological Modelling in QGIS".
MOLUSCE is a NextGIS plugin; QGIS and SWAT+ belong to their respective projects. This project is not affiliated with them.

## Licence
MIT (see LICENSE).
