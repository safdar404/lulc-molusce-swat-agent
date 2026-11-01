# Contributing
- `pip install -r requirements-dev.txt`, then `pytest -q` and `ruff check .` before every pull request.
- Put pure statistics in `src/lulc_core/metrics.py` with a test that compares against a hand-computed value.
- After editing `metrics.py` or `knowledge.py`, run `python scripts/sync_plugin.py` so the QGIS plugin copy matches.
- Never add real or confidential geodata, API keys or `.streamlit/secrets.toml` to the repository.
- New tools must be read-only unless a user-approval step is added; outputs must never overwrite files.
