# Contributing
- `pip install -r requirements-dev.txt`, then `pytest -q` and `ruff check .` before every pull request.
- Put pure statistics in `metrics.py` with a test in `test_core.py` that compares against a hand-computed value.
- Keep the flat layout: new modules go in the repository root and use absolute imports (`import metrics`, not `from . import metrics`).
- Never add real or confidential geodata, API keys or `.streamlit/secrets.toml` to the repository.
- New tools must be read-only unless a user-approval step is added; outputs must never overwrite files.
