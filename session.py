"""Session = store + tables + audit log. Every tool call is logged in the manual's template format."""
import datetime, json
import numpy as np, pandas as pd, rasterio
from store import Store


class Session:
    def __init__(self):
        self.store, self.tables, self.log = Store(), {}, []

    def env(self):
        return f"numpy {np.__version__}; pandas {pd.__version__}; rasterio {rasterio.__version__}"

    def record(self, tool, args, output="", note=""):
        self.log.append(dict(date=datetime.datetime.now().isoformat(timespec="seconds"), input=tool, tool_version=self.env(),
                             parameters=json.dumps(args, default=str)[:600], output=str(output)[:300], reason_note=note))

    def log_df(self):
        cols = ["date", "input", "tool_version", "parameters", "output", "reason_note"]
        return pd.DataFrame(self.log, columns=cols)

    def call(self, name, args=None):
        from agent_tools import run_tool
        return run_tool(self, name, args or {})
