# Changelog
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
