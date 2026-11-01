"""Pure-numpy statistics (no QGIS needed, so they can be unit-tested)."""
import numpy as np


def confusion_matrix(ref, pred, classes=None):
    ref = np.asarray(ref).ravel()
    pred = np.asarray(pred).ravel()
    if ref.shape != pred.shape:
        raise ValueError("ref and pred must have the same size")
    cls = np.array(sorted(set(np.unique(ref)) | set(np.unique(pred))) if classes is None else sorted(classes))
    ok = np.isin(ref, cls) & np.isin(pred, cls)
    n = len(cls)
    ri, pi = np.searchsorted(cls, ref[ok]), np.searchsorted(cls, pred[ok])
    m = np.bincount(ri * n + pi, minlength=n * n).reshape(n, n)
    return m, cls.tolist()


def _div(a, b):
    return np.divide(a, b, out=np.full(np.shape(a), np.nan, dtype=float), where=np.asarray(b) != 0)


def accuracy_from_matrix(m):
    """Rows = reference, columns = predicted."""
    m = np.asarray(m, dtype=float)
    n = m.sum()
    if n == 0:
        raise ValueError("empty confusion matrix")
    diag = np.diag(m)
    oa = diag.sum() / n
    pe = (m.sum(1) * m.sum(0)).sum() / n ** 2
    kappa = (oa - pe) / (1 - pe) if pe < 1 else float("nan")
    return dict(n=int(n), overall_accuracy=float(oa), kappa=float(kappa),
                producers_accuracy=_div(diag, m.sum(1)).tolist(),
                users_accuracy=_div(diag, m.sum(0)).tolist())


def pontius_disagreement(m):
    """Quantity and allocation disagreement (Pontius & Millones 2011)."""
    p = np.asarray(m, dtype=float)
    p = p / p.sum()
    total = 1 - np.trace(p)
    quantity = np.abs(p.sum(1) - p.sum(0)).sum() / 2
    return dict(total=float(total), quantity=float(quantity), allocation=float(total - quantity))


def figure_of_merit(initial, observed, simulated):
    i, o, s = (np.asarray(x).ravel() for x in (initial, observed, simulated))
    oc, sc = o != i, s != i
    hits = int((oc & sc & (o == s)).sum())
    misses = int((oc & ~sc).sum())
    false_alarms = int((~oc & sc).sum())
    wrong_hits = int((oc & sc & (o != s)).sum())
    den = hits + misses + false_alarms + wrong_hits
    return dict(hits=hits, misses=misses, false_alarms=false_alarms, wrong_hits=wrong_hits,
                fom=float(hits / den) if den else float("nan"))


def area_ha(pixel_counts, pixel_area_m2):
    return (np.asarray(pixel_counts, dtype=float) * pixel_area_m2 / 10000.0).tolist()


def pct_change(a1, a2):
    return float((a2 - a1) / a1 * 100) if a1 else float("nan")


def _pair(obs, sim):
    o, s = np.asarray(obs, float).ravel(), np.asarray(sim, float).ravel()
    ok = np.isfinite(o) & np.isfinite(s)
    if ok.sum() < 2:
        raise ValueError("need at least 2 valid pairs")
    return o[ok], s[ok]


def nse(obs, sim):
    o, s = _pair(obs, sim)
    den = ((o - o.mean()) ** 2).sum()
    return float(1 - ((o - s) ** 2).sum() / den) if den else float("nan")


def pbias(obs, sim):
    """Manual convention: 100 * sum(obs - sim) / sum(obs); positive = underestimation."""
    o, s = _pair(obs, sim)
    return float(100 * (o - s).sum() / o.sum()) if o.sum() else float("nan")


def r2(obs, sim):
    o, s = _pair(obs, sim)
    if o.std() == 0 or s.std() == 0:
        return float("nan")
    return float(np.corrcoef(o, s)[0, 1] ** 2)


def kge(obs, sim):
    o, s = _pair(obs, sim)
    if o.std() == 0 or o.mean() == 0 or s.std() == 0:
        return float("nan")
    r = np.corrcoef(o, s)[0, 1]
    a, b = s.std() / o.std(), s.mean() / o.mean()
    return float(1 - np.sqrt((r - 1) ** 2 + (a - 1) ** 2 + (b - 1) ** 2))
