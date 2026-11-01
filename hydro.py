import pandas as pd
from . import metrics


def align(obs_df, sim_df, date_col, obs_col, sim_col, start=None, end=None):
    o = pd.DataFrame({"date": pd.to_datetime(obs_df[date_col], errors="coerce"), "obs": pd.to_numeric(obs_df[obs_col], errors="coerce")})
    s = pd.DataFrame({"date": pd.to_datetime(sim_df[date_col], errors="coerce"), "sim": pd.to_numeric(sim_df[sim_col], errors="coerce")})
    m = o.merge(s, on="date").dropna()
    if start:
        m = m[m["date"] >= pd.to_datetime(start)]
    if end:
        m = m[m["date"] <= pd.to_datetime(end)]
    return m.sort_values("date").reset_index(drop=True)


def compute(obs_df, sim_df, date_col, obs_col, sim_col, start=None, end=None):
    m = align(obs_df, sim_df, date_col, obs_col, sim_col, start, end)
    if len(m) < 2:
        raise ValueError("Fewer than 2 matching dates in the chosen period.")
    return dict(n_pairs=len(m), first=str(m["date"].iloc[0].date()), last=str(m["date"].iloc[-1].date()),
                nse=metrics.nse(m["obs"], m["sim"]), pbias_percent=metrics.pbias(m["obs"], m["sim"]),
                r2=metrics.r2(m["obs"], m["sim"]), kge=metrics.kge(m["obs"], m["sim"]),
                caution="Do not tune on the validation period. Inspect hydrograph shape, peaks and seasonality; "
                        "thresholds for 'acceptable' depend on time step and variable.")
