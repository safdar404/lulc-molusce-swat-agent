# Changelog
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
