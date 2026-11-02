"""
Area-adjusted accuracy assessment for categorical (LULC) maps.

Implements
----------
* Olofsson et al. (2013, 2014) good-practice estimators for stratified random
  sampling where map classes are the strata:
    - area-proportion error matrix
    - overall, user's and producer's accuracy with standard errors
    - error-adjusted area per class with 95 % confidence intervals
* Pontius & Millones (2011) quantity and allocation disagreement, and the
  Pontius & Santacruz (2014) split of allocation into exchange and shift.
* Cochran / Olofsson (2014, Eq. 13) sample-size planning and allocation.
* Cohen's kappa on sample counts (reported for continuity only; see
  Pontius & Millones 2011 on why it should not be the headline metric).

Conventions
-----------
Rows = map (classified) class, columns = reference class.
All functions are pure numpy/pandas so they can be unit tested and called by
the Streamlit UI or by the AI agent as a tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

Z95 = 1.959964


# --------------------------------------------------------------------------- #
# Building the sample error matrix
# --------------------------------------------------------------------------- #
def sample_error_matrix(map_labels: Sequence, ref_labels: Sequence,
                        classes: Sequence | None = None) -> pd.DataFrame:
    """Cross-tabulate sample counts n_ij (rows = map, cols = reference)."""
    m = pd.Series(list(map_labels), name="map")
    r = pd.Series(list(ref_labels), name="reference")
    if classes is None:
        classes = sorted(set(m.dropna()) | set(r.dropna()), key=lambda v: str(v))
    ct = pd.crosstab(m, r).reindex(index=classes, columns=classes, fill_value=0)
    ct.index.name, ct.columns.name = "map", "reference"
    return ct.astype(int)


# --------------------------------------------------------------------------- #
# Olofsson estimators
# --------------------------------------------------------------------------- #
@dataclass
class AccuracyResult:
    classes: list
    n: np.ndarray                 # sample counts (k x k)
    mapped_area: np.ndarray       # mapped area per class (area units)
    total_area: float
    area_unit: str
    p: np.ndarray                 # area-proportion matrix
    overall: float
    overall_se: float
    users: np.ndarray
    users_se: np.ndarray
    producers: np.ndarray
    producers_se: np.ndarray
    area_prop: np.ndarray         # estimated reference proportion per class
    area_prop_se: np.ndarray
    kappa: float
    pontius: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    # ---- convenience views ------------------------------------------------ #
    @property
    def area(self) -> np.ndarray:
        return self.area_prop * self.total_area

    @property
    def area_ci95(self) -> np.ndarray:
        return Z95 * self.area_prop_se * self.total_area

    def proportion_matrix_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self.p, index=self.classes, columns=self.classes)
        df["Total (map)"] = df.sum(axis=1)
        df.loc["Total (reference)"] = df.sum(axis=0)
        df.index.name, df.columns.name = "map", "reference"
        return df

    def sample_matrix_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self.n, index=self.classes, columns=self.classes)
        df["n_i (map)"] = df.sum(axis=1)
        df.loc["n_j (reference)"] = df.sum(axis=0)
        df.index.name, df.columns.name = "map", "reference"
        return df

    def class_table(self) -> pd.DataFrame:
        u = self.area_unit
        return pd.DataFrame({
            "class": self.classes,
            "n_samples (map)": self.n.sum(axis=1),
            "W_i (map weight)": self.mapped_area / self.total_area,
            f"mapped area ({u})": self.mapped_area,
            f"adjusted area ({u})": self.area,
            f"± 95% CI ({u})": self.area_ci95,
            "CI as % of area": np.where(self.area > 0,
                                        100 * self.area_ci95 / np.where(self.area > 0, self.area, 1),
                                        np.nan),
            "user's acc.": self.users,
            "user's ± 95%": Z95 * self.users_se,
            "producer's acc.": self.producers,
            "producer's ± 95%": Z95 * self.producers_se,
            "F1": _f1(self.users, self.producers),
        })

    def summary(self) -> dict:
        """JSON-serialisable summary (for the AI agent / report generator)."""
        ct = self.class_table()
        return {
            "overall_accuracy": round(float(self.overall), 4),
            "overall_accuracy_ci95": round(float(Z95 * self.overall_se), 4),
            "kappa_sample_counts": round(float(self.kappa), 4),
            "pontius": {k: round(float(v), 4) if isinstance(v, (float, np.floating)) else v
                        for k, v in self.pontius.items() if k != "per_class"},
            "total_area": float(self.total_area),
            "area_unit": self.area_unit,
            "classes": _records(ct),
            "warnings": self.warnings,
        }

    def methods_text(self) -> str:
        """Ready-to-paste methods/results paragraph for a paper or report."""
        k = len(self.classes)
        n_tot = int(self.n.sum())
        u = self.area_unit
        lines = [
            f"Accuracy was assessed with a stratified random sample of {n_tot} "
            f"reference points, using the {k} map classes as strata. Following "
            "Olofsson et al. (2014), sample counts were converted to an "
            "area-proportion error matrix by weighting each map stratum by its "
            "mapped proportion, from which overall, user's and producer's "
            "accuracies and error-adjusted (unbiased) class areas were estimated "
            "with 95% confidence intervals.",
            f"Overall accuracy was {100*self.overall:.1f}% "
            f"(± {100*Z95*self.overall_se:.1f}%). Total disagreement "
            f"({100*(1-self.overall):.1f}%) comprised quantity disagreement of "
            f"{100*self.pontius['quantity']:.1f}% and allocation disagreement of "
            f"{100*self.pontius['allocation']:.1f}% (Pontius & Millones, 2011).",
        ]
        parts = []
        for c, a, ci, ma in zip(self.classes, self.area, self.area_ci95, self.mapped_area):
            parts.append(f"{c}: {a:,.1f} ± {ci:,.1f} {u} (mapped {ma:,.1f})")
        lines.append("Error-adjusted areas — " + "; ".join(parts) + ".")
        return "\n\n".join(lines)


def _f1(u, p):
    u, p = np.asarray(u, float), np.asarray(p, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((u + p) > 0, 2 * u * p / (u + p), np.nan)


def _records(df: pd.DataFrame) -> list:
    out = []
    for rec in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and np.isnan(v)
                        else round(float(v), 4) if isinstance(v, (float, np.floating))
                        else int(v) if isinstance(v, (np.integer,)) else v)
                    for k, v in rec.items()})
    return out


def olofsson_accuracy(n: pd.DataFrame | np.ndarray,
                      mapped_area: Sequence[float],
                      classes: Sequence | None = None,
                      area_unit: str = "ha") -> AccuracyResult:
    """
    Olofsson et al. (2014) estimators.

    Parameters
    ----------
    n : (k x k) sample counts, rows = map class, cols = reference class.
    mapped_area : mapped area (or pixel count) of each map class, same order.
    area_unit : label for the area units supplied.
    """
    if isinstance(n, pd.DataFrame):
        classes = list(n.index) if classes is None else list(classes)
        n = n.to_numpy()
    n = np.asarray(n, dtype=float)
    k = n.shape[0]
    if n.shape != (k, k):
        raise ValueError("Error matrix must be square.")
    classes = list(classes) if classes is not None else [f"class_{i+1}" for i in range(k)]
    A = np.asarray(mapped_area, dtype=float)
    if A.shape != (k,):
        raise ValueError("mapped_area must have one value per class.")
    warnings: list[str] = []

    A_tot = A.sum()
    W = A / A_tot
    n_i = n.sum(axis=1)

    for c, ni, Wi in zip(classes, n_i, W):
        if ni == 0 and Wi > 0:
            warnings.append(f"Map class '{c}' has mapped area but no samples; its "
                            "row contributes nothing and estimates are biased.")
        elif 0 < ni < 2:
            warnings.append(f"Map class '{c}' has <2 samples; variance undefined.")
        elif 0 < ni < 30:
            warnings.append(f"Map class '{c}' has only {int(ni)} samples; CIs will be wide "
                            "(Olofsson et al. recommend ≥50 per class).")

    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(n_i[:, None] > 0, n / n_i[:, None], 0.0)   # n_ij / n_i.
    p = W[:, None] * frac                                           # p_ij
    denom = np.where(n_i > 1, n_i - 1, np.nan)

    # Overall accuracy
    U = np.diag(frac).copy()
    U[n_i == 0] = np.nan
    OA = float(np.trace(p))
    var_OA = np.nansum(W**2 * U * (1 - U) / denom)

    # User's accuracy
    var_U = U * (1 - U) / denom

    # Producer's accuracy (Olofsson 2014 Eq. 7 using pixel/area totals)
    N_i = A                                     # mapped totals per class
    N_j = (N_i[:, None] * frac).sum(axis=0)     # estimated reference totals
    p_col = p.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        P = np.diag(p) / p_col
    var_P = np.full(k, np.nan)
    for j in range(k):
        if N_j[j] <= 0 or not np.isfinite(P[j]):
            continue
        term1 = (N_i[j]**2 * (1 - P[j])**2 * U[j] * (1 - U[j]) / denom[j]
                 if n_i[j] > 1 else 0.0)
        term2 = 0.0
        for i in range(k):
            if i == j or n_i[i] <= 1:
                continue
            f = frac[i, j]
            term2 += N_i[i]**2 * f * (1 - f) / (n_i[i] - 1)
        var_P[j] = (term1 + P[j]**2 * term2) / N_j[j]**2

    # Area proportions and SE (Olofsson 2014 Eq. 10)
    se_area = np.sqrt(np.nansum((W[:, None] * p - p**2) / denom[:, None], axis=0))

    # Kappa on sample counts
    N = n.sum()
    po = np.trace(n) / N if N else np.nan
    pe = (n.sum(1) * n.sum(0)).sum() / N**2 if N else np.nan
    kappa = (po - pe) / (1 - pe) if N and pe != 1 else np.nan

    return AccuracyResult(
        classes=classes, n=n.astype(int), mapped_area=A, total_area=A_tot,
        area_unit=area_unit, p=p, overall=OA, overall_se=float(np.sqrt(var_OA)),
        users=U, users_se=np.sqrt(var_U), producers=P, producers_se=np.sqrt(var_P),
        area_prop=p_col, area_prop_se=se_area, kappa=float(kappa),
        pontius=pontius_components(p, classes), warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Pontius components
# --------------------------------------------------------------------------- #
def pontius_components(p: np.ndarray, classes: Sequence | None = None) -> dict:
    """
    Quantity / allocation (Pontius & Millones 2011) and exchange / shift
    (Pontius & Santacruz 2014) from a proportion matrix (sums to 1).
    """
    p = np.asarray(p, float)
    p = p / p.sum()
    k = p.shape[0]
    classes = list(classes) if classes is not None else list(range(k))
    row, col, diag = p.sum(1), p.sum(0), np.diag(p)
    q_g = np.abs(row - col)
    a_g = 2 * np.minimum(row - diag, col - diag)
    Q, Aloc = q_g.sum() / 2, a_g.sum() / 2
    exch = 0.0
    exch_g = np.zeros(k)
    for i in range(k):
        for j in range(i + 1, k):
            e = 2 * min(p[i, j], p[j, i])
            exch += e
            exch_g[i] += e
            exch_g[j] += e
    shift = Aloc - exch
    per_class = pd.DataFrame({
        "class": classes, "quantity": q_g, "allocation": a_g,
        "exchange": exch_g, "shift": a_g - exch_g,
    })
    return {"total_disagreement": 1 - diag.sum(), "quantity": Q,
            "allocation": Aloc, "exchange": exch, "shift": shift,
            "per_class": per_class}


# --------------------------------------------------------------------------- #
# Sample-size design
# --------------------------------------------------------------------------- #
def sample_size_design(mapped_area: Sequence[float], expected_users: Sequence[float],
                       target_se_overall: float = 0.01,
                       allocation: str = "olofsson", min_per_class: int = 50,
                       classes: Sequence | None = None) -> pd.DataFrame:
    """
    Total n from Cochran (1977) / Olofsson et al. (2014) Eq. 13:
        n = (Σ W_i S_i / S(Ô))²,  S_i = sqrt(U_i (1 − U_i))
    then allocate to strata.

    allocation:
      'proportional' – n_i ∝ W_i
      'equal'        – n / k each
      'neyman'       – n_i ∝ W_i S_i
      'olofsson'     – each class gets at least `min_per_class`; the rest
                       proportional (the compromise recommended in the paper).
    """
    A = np.asarray(mapped_area, float)
    U = np.clip(np.asarray(expected_users, float), 1e-6, 1 - 1e-6)
    k = len(A)
    classes = list(classes) if classes is not None else [f"class_{i+1}" for i in range(k)]
    W = A / A.sum()
    S = np.sqrt(U * (1 - U))
    n_total = int(np.ceil((np.sum(W * S) / target_se_overall) ** 2))

    if allocation == "proportional":
        alloc = W * n_total
    elif allocation == "equal":
        alloc = np.full(k, n_total / k)
    elif allocation == "neyman":
        alloc = W * S / np.sum(W * S) * n_total
    elif allocation == "olofsson":
        alloc = W * n_total
        small = alloc < min_per_class
        alloc[small] = min_per_class
        remaining = max(n_total - alloc[small].sum(), 0)
        if (~small).any():
            alloc[~small] = W[~small] / W[~small].sum() * remaining
            # a large class could now fall under the minimum
            alloc = np.maximum(alloc, min_per_class)
    else:
        raise ValueError("allocation must be proportional | equal | neyman | olofsson")

    alloc = np.ceil(alloc).astype(int)
    return pd.DataFrame({"class": classes, "W_i": W, "expected_UA": U,
                         "S_i": S, "n_samples": alloc}) \
             .assign(n_total_formula=n_total)
