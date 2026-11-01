# Changelog
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
