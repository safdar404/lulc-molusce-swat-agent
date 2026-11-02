"""
Intensity Analysis of land change across multiple time intervals.

Implements
----------
* Aldwaik & Pontius (2012) Intensity Analysis at three levels
    - Interval    : annual change intensity S_t vs uniform U  (fast / slow)
    - Category    : gross gain G_tj and loss L_ti vs S_t      (active / dormant)
    - Transition  : R_tin vs W_tn (gain of n targets / avoids i)
                    Q_tmj vs V_tm (loss of m targets / avoids j)
* Stationarity of category- and transition-level patterns across intervals
  (Aldwaik & Pontius 2012, Sec. 2.5)
* Change components per category: gross gain, gross loss, net, swap
  (Pontius et al. 2004), and alternation across intervals
  (Pontius et al. 2017: sum of interval changes − extent change)

Input is a list of square transition matrices (area units), rows = category at
the START of the interval, columns = category at the END, plus the years of
each time point. Everything is pure numpy/pandas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass
class IntensityResult:
    classes: list
    years: list
    matrices: list            # list of (k x k) arrays
    area_unit: str
    interval: pd.DataFrame
    category: pd.DataFrame
    transition_gain: pd.DataFrame
    transition_loss: pd.DataFrame
    stationarity_category: pd.DataFrame
    stationarity_transition: pd.DataFrame
    components: pd.DataFrame
    uniform_U: float

    # ------------------------------------------------------------------ #
    def matrix_df(self, t: int) -> pd.DataFrame:
        m = pd.DataFrame(self.matrices[t], index=self.classes, columns=self.classes)
        m["Total (start)"] = m.sum(axis=1)
        m.loc["Total (end)"] = m.sum(axis=0)
        m.index.name = f"{self.years[t]} \\ {self.years[t+1]}"
        return m

    def summary(self, max_items: int = 30) -> dict:
        def recs(df, cols):
            return df[cols].round(4).to_dict(orient="records")[:max_items]
        tg = self.transition_gain[self.transition_gain["status"] == "targeted"]
        tl = self.transition_loss[self.transition_loss["status"] == "targeted"]
        return {
            "years": self.years, "area_unit": self.area_unit,
            "uniform_intensity_U_pct_per_yr": round(self.uniform_U, 4),
            "interval_level": recs(self.interval, ["interval", "change_area",
                                                   "S_annual_pct", "speed"]),
            "category_level": recs(self.category, ["interval", "category", "gross_gain",
                                                   "gross_loss", "G_gain_intensity", "gain_status",
                                                   "L_loss_intensity", "loss_status"]),
            "targeted_gain_transitions": recs(tg, ["interval", "to", "from", "area",
                                                   "R_intensity", "W_uniform"]),
            "targeted_loss_transitions": recs(tl, ["interval", "from", "to", "area",
                                                   "Q_intensity", "V_uniform"]),
            "category_stationarity": self.stationarity_category.to_dict(orient="records"),
            "components": recs(self.components, list(self.components.columns)),
        }

    def methods_text(self) -> str:
        it = self.interval
        k, T = len(self.classes), len(self.years)
        u = self.area_unit
        s = [
            f"Land change among {k} categories was analysed for {T} time points "
            f"({', '.join(map(str, self.years))}) using Intensity Analysis "
            "(Aldwaik & Pontius, 2012) at the interval, category and transition levels. "
            "Annual change intensities were compared with uniform intensities to identify "
            "fast versus slow intervals, active versus dormant categories, and targeted "
            "versus avoided transitions.",
        ]
        parts = [f"{r.interval}: {r.S_annual_pct:.2f}%/yr ({r.speed})" for r in it.itertuples()]
        s.append(f"The uniform annual change intensity was {self.uniform_U:.2f}% of the "
                 f"study area; interval intensities were " + "; ".join(parts) + ".")
        cat = self.category
        act_g = cat[cat.gain_status == "active"].groupby("category")["interval"].count()
        act_l = cat[cat.loss_status == "active"].groupby("category")["interval"].count()
        nI = len(it)
        sg = [c for c, n in act_g.items() if n == nI]
        sl = [c for c, n in act_l.items() if n == nI]
        if sg:
            s.append("Gains were stationary-active (active in every interval) for: "
                     + ", ".join(map(str, sg)) + ".")
        if sl:
            s.append("Losses were stationary-active for: " + ", ".join(map(str, sl)) + ".")
        top = self.transition_gain[self.transition_gain.status == "targeted"] \
            .sort_values("area", ascending=False).head(3)
        if len(top):
            s.append("The largest targeted transitions were " + "; ".join(
                f"{r['from']}→{r['to']} in {r['interval']} ({r['area']:,.1f} {u}, "
                f"R={r['R_intensity']:.2f} vs W={r['W_uniform']:.2f}%/yr)"
                for r in top.to_dict(orient="records")) + ".")
        comp = self.components
        alt = comp[comp["alternation"] > 0]
        if T > 2 and len(alt):
            s.append("Alternation (change reversed between intervals) was largest for "
                     + ", ".join(f"{r.category} ({r.alternation:,.1f} {u})"
                                 for r in alt.sort_values("alternation", ascending=False)
                                 .head(3).itertuples()) + ".")
        return "\n\n".join(s)


def _status(x, ref, hi, lo):
    return np.where(np.isnan(x), "n/a", np.where(x > ref, hi, lo))


def intensity_analysis(matrices: Sequence[np.ndarray], years: Sequence[float],
                       classes: Sequence | None = None, area_unit: str = "ha") -> IntensityResult:
    mats = [np.asarray(m, float) for m in matrices]
    k = mats[0].shape[0]
    if any(m.shape != (k, k) for m in mats):
        raise ValueError("All transition matrices must be k x k with the same k.")
    years = list(years)
    if len(years) != len(mats) + 1:
        raise ValueError("Need len(years) == number of matrices + 1.")
    if any(b <= a for a, b in zip(years, years[1:])):
        raise ValueError("Years must be strictly increasing.")
    classes = list(classes) if classes is not None else [f"class_{i+1}" for i in range(k)]
    totals = [m.sum() for m in mats]
    if max(totals) - min(totals) > 1e-6 * max(totals):
        raise ValueError("Study-area extent differs between intervals; use a common mask.")
    extent = totals[0]

    iv_rows, cat_rows, tg_rows, tl_rows = [], [], [], []
    total_change = 0.0
    for t, m in enumerate(mats):
        y0, y1 = years[t], years[t + 1]
        d = y1 - y0
        lab = f"{y0}–{y1}"
        start, end, diag = m.sum(1), m.sum(0), np.diag(m)
        change = m.sum() - diag.sum()
        total_change += change
        S = change / d / extent * 100
        iv_rows.append(dict(interval=lab, years=d, change_area=change,
                            change_pct_extent=change / extent * 100, S_annual_pct=S))

        gain, loss = end - diag, start - diag
        with np.errstate(invalid="ignore", divide="ignore"):
            G = np.where(end > 0, gain / d / end * 100, np.nan)
            L = np.where(start > 0, loss / d / start * 100, np.nan)
        for i, c in enumerate(classes):
            cat_rows.append(dict(interval=lab, category=c, start_area=start[i], end_area=end[i],
                                 persistence=diag[i], gross_gain=gain[i], gross_loss=loss[i],
                                 net_change=gain[i] - loss[i],
                                 swap=2 * min(gain[i], loss[i]),
                                 G_gain_intensity=G[i], L_loss_intensity=L[i], S_annual_pct=S))

        # transition level — gain of n
        for n in range(k):
            others = [i for i in range(k) if i != n]
            denom = start[others].sum()
            W = gain[n] / d / denom * 100 if denom > 0 else np.nan
            for i in others:
                R = m[i, n] / d / start[i] * 100 if start[i] > 0 else np.nan
                tg_rows.append({"interval": lab, "to": classes[n], "from": classes[i],
                                "area": m[i, n], "R_intensity": R, "W_uniform": W})
        # transition level — loss of m
        for mm in range(k):
            others = [j for j in range(k) if j != mm]
            denom = end[others].sum()
            V = loss[mm] / d / denom * 100 if denom > 0 else np.nan
            for j in others:
                Q = m[mm, j] / d / end[j] * 100 if end[j] > 0 else np.nan
                tl_rows.append({"interval": lab, "from": classes[mm], "to": classes[j],
                                "area": m[mm, j], "Q_intensity": Q, "V_uniform": V})

    U = total_change / (years[-1] - years[0]) / extent * 100
    interval = pd.DataFrame(iv_rows)
    interval["U_uniform_pct"] = U
    interval["speed"] = np.where(interval["S_annual_pct"] > U, "fast", "slow")

    category = pd.DataFrame(cat_rows)
    category["gain_status"] = _status(category.G_gain_intensity.to_numpy(),
                                      category.S_annual_pct.to_numpy(), "active", "dormant")
    category["loss_status"] = _status(category.L_loss_intensity.to_numpy(),
                                      category.S_annual_pct.to_numpy(), "active", "dormant")

    tg = pd.DataFrame(tg_rows)
    tg["status"] = _status(tg.R_intensity.to_numpy(), tg.W_uniform.to_numpy(), "targeted", "avoided")
    tl = pd.DataFrame(tl_rows)
    tl["status"] = _status(tl.Q_intensity.to_numpy(), tl.V_uniform.to_numpy(), "targeted", "avoided")

    # stationarity (consistent across all intervals)
    def stationarity(series):
        vals = set(series) - {"n/a"}
        return f"stationary {vals.pop()}" if len(vals) == 1 else "non-stationary"

    st_cat = category.groupby("category", sort=False).agg(
        gain=("gain_status", stationarity), loss=("loss_status", stationarity)).reset_index()
    st_tr = pd.concat([
        tg.groupby(["to", "from"], sort=False)["status"].agg(stationarity)
          .rename("gain_pattern").reset_index().rename(columns={"to": "category", "from": "other"}),
    ])
    st_tr_loss = tl.groupby(["from", "to"], sort=False)["status"].agg(stationarity) \
        .rename("loss_pattern").reset_index().rename(columns={"from": "category", "to": "other"})
    st_tr = st_tr.merge(st_tr_loss, on=["category", "other"], how="outer")

    # components across the whole period
    comp_rows = []
    sum_gain = category.groupby("category", sort=False)["gross_gain"].sum()
    sum_loss = category.groupby("category", sort=False)["gross_loss"].sum()
    for i, c in enumerate(classes):
        comp_rows.append(dict(category=c, sum_interval_gain=sum_gain[c],
                              sum_interval_loss=sum_loss[c]))
    comp = pd.DataFrame(comp_rows)
    comp["net_change_period"] = category.groupby("category", sort=False)["net_change"].sum().values
    comp["start_area"] = mats[0].sum(1)
    comp["end_area"] = mats[-1].sum(0)
    comp["alternation"] = np.nan  # filled when an extent (first→last) matrix is given
    return IntensityResult(classes, years, mats, area_unit, interval, category, tg, tl,
                           st_cat, st_tr, comp, float(U))


def add_extent_components(res: IntensityResult, extent_matrix: np.ndarray) -> IntensityResult:
    """
    Pontius et al. (2017): alternation = Σ interval gross change − extent change
    (first→last). Requires the first→last transition matrix (pixel-level).
    """
    e = np.asarray(extent_matrix, float)
    diag = np.diag(e)
    ext_gain, ext_loss = e.sum(0) - diag, e.sum(1) - diag
    c = res.components
    c["extent_gain"] = ext_gain
    c["extent_loss"] = ext_loss
    c["extent_net"] = ext_gain - ext_loss
    c["extent_swap"] = 2 * np.minimum(ext_gain, ext_loss)
    c["alternation"] = (c["sum_interval_gain"] + c["sum_interval_loss"]
                        - ext_gain - ext_loss) / 2
    return res
