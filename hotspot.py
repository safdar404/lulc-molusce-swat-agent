"""Spatial hotspot statistics on a raster grid (binary distance-band weights, square or circular window).

* Global Moran's I with normality-based z-score (Cliff & Ord 1981)
* Getis-Ord Gi* z-scores (Getis & Ord 1992; Ord & Getis 1995), 90/95/99 % hot/cold bins, optional
  Benjamini-Hochberg false-discovery-rate correction
* Local Moran's I (Anselin 1995) with row-standardised weights and conditional-permutation pseudo p-values,
  giving High-High / Low-Low / High-Low / Low-High cluster maps

All neighbourhood sums are convolutions, so the cost is linear in the number of cells.
"""
import math

import numpy as np
from scipy import ndimage
from scipy.special import ndtr as _ndtr


def kernel(radius, shape="square"):
    r = int(radius)
    if r < 1:
        raise ValueError("radius must be >= 1 cell")
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    k = np.ones_like(x, float) if shape == "square" else (x * x + y * y <= r * r + 1e-9).astype(float)
    return k


def _conv(a, k):
    return ndimage.convolve(a, k, mode="constant", cval=0.0)


def aggregate(x, valid, factor, min_frac=0.5):
    """Block mean over factor x factor cells; blocks with < min_frac valid cells become invalid."""
    f = int(factor)
    if f <= 1:
        return x.astype(float), valid.copy()
    H, W = x.shape
    h, w = -(-H // f), -(-W // f)
    xp = np.zeros((h * f, w * f))
    vp = np.zeros((h * f, w * f))
    xp[:H, :W] = np.where(valid, x, 0)
    vp[:H, :W] = valid
    s = xp.reshape(h, f, w, f).sum((1, 3))
    n = vp.reshape(h, f, w, f).sum((1, 3))
    ok = n >= min_frac * f * f
    return np.where(ok, s / np.maximum(n, 1), np.nan), ok


def fdr_bh(p, alpha_levels=(0.01, 0.05, 0.10)):
    """Benjamini-Hochberg adjusted p-values (vector)."""
    p = np.asarray(p, float)
    n = p.size
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(adj, 0, 1)
    return out


def _bins(z, p):
    conf = np.where(p < 0.01, 3, np.where(p < 0.05, 2, np.where(p < 0.10, 1, 0)))
    return (np.sign(z) * conf).astype("int8")


def global_moran(x, valid, k):
    """Global Moran's I with binary weights (self excluded) and normality z."""
    kk = k.copy()
    c = kk.shape[0] // 2
    kk[c, c] = 0
    v = valid.astype(float)
    xv = x[valid]
    n = xv.size
    z = np.zeros(x.shape)
    z[valid] = xv - xv.mean()
    lag = _conv(z, kk)
    wi = _conv(v, kk) * v                 # neighbour count of each valid cell
    S0 = wi.sum()
    m2 = (z[valid] ** 2).sum()
    if S0 == 0 or m2 == 0:
        return dict(I=np.nan, expected=np.nan, z=np.nan, p=np.nan)
    I = n / S0 * (z * lag)[valid].sum() / m2
    S1 = 2 * S0                            # symmetric binary weights
    S2 = 4 * (wi[valid] ** 2).sum()
    EI = -1 / (n - 1)
    VI = (n * n * S1 - n * S2 + 3 * S0 * S0) / ((n * n - 1) * S0 * S0) - EI * EI
    zI = (I - EI) / math.sqrt(VI)
    return dict(I=float(I), expected=float(EI), z=float(zI), p=float(2 * (1 - _ndtr(abs(zI)))))


def gi_star(x, valid, k, fdr=True):
    """Getis-Ord Gi* (self included) for every valid cell. Returns z, p, bins (-3..3)."""
    v = valid.astype(float)
    xv = np.where(valid, x, 0.0)
    n = valid.sum()
    xbar = xv[valid].mean()
    s = math.sqrt(max((xv[valid] ** 2).mean() - xbar * xbar, 0.0))
    sw = _conv(v, k)                       # Σ w (binary) over valid neighbours incl. self
    swx = _conv(xv, k)
    sw2 = _conv(v, k * k)
    denom = s * np.sqrt(np.maximum((n * sw2 - sw * sw) / (n - 1), 0))
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(valid & (denom > 0), (swx - xbar * sw) / denom, np.nan)
    p = np.full(x.shape, np.nan)
    p[valid] = 2 * (1 - _ndtr(np.abs(np.nan_to_num(z[valid]))))
    if fdr:
        p[valid] = fdr_bh(p[valid])
    bins = np.zeros(x.shape, "int8")
    bins[valid] = _bins(np.nan_to_num(z[valid]), p[valid])
    return z, p, bins


def local_moran(x, valid, k, permutations=199, alpha=0.05, seed=12345, fdr=False):
    """Local Moran's I (row-standardised), conditional permutation inference.
    Returns I, pseudo-p, quadrant (1 HH, 2 LH, 3 LL, 4 HL) and significant cluster map (0 = not significant)."""
    kk = k.copy()
    c = kk.shape[0] // 2
    kk[c, c] = 0
    v = valid.astype(float)
    xv = x[valid]
    n = xv.size
    z = np.zeros(x.shape)
    z[valid] = xv - xv.mean()
    m2 = (z[valid] ** 2).sum() / (n - 1)  # PySAL/GeoDa convention
    wi = _conv(v, kk)
    with np.errstate(invalid="ignore", divide="ignore"):
        lag = np.where(wi > 0, _conv(z, kk) / wi, 0.0)
    Ii = np.full(x.shape, np.nan)
    Ii[valid] = z[valid] * lag[valid] / m2
    q = np.zeros(x.shape, "uint8")
    zp, lp = z[valid] > 0, lag[valid] > 0
    q[valid] = np.select([zp & lp, ~zp & lp, ~zp & ~lp, zp & ~lp], [1, 2, 3, 4])

    # conditional permutation: for cell i draw w_i values from the other n-1 cells
    zi, ki = z[valid], wi[valid].astype(int)
    K = int(ki.max()) if ki.size else 0
    obs = Ii[valid]
    larger = np.zeros(n)
    rng = np.random.default_rng(seed)
    self_idx = np.arange(n)[:, None]
    take = np.arange(K)[None, :] < ki[:, None]
    for _ in range(int(permutations)):
        r = rng.integers(0, n - 1, size=(n, K))
        r += r >= self_idx                 # skip self
        sim_lag = np.where(take, zi[r], 0).sum(1) / np.maximum(ki, 1)
        larger += (zi * sim_lag / m2) >= obs
    larger = np.where(permutations - larger < larger, permutations - larger, larger)
    p = np.full(x.shape, np.nan)
    p[valid] = (larger + 1) / (permutations + 1)
    if fdr:
        p[valid] = fdr_bh(p[valid])
    clusters = np.where(valid & (p < alpha), q, 0).astype("uint8")
    return Ii, p, q, clusters


CLUSTER_NAMES = {0: "not significant", 1: "High-High", 2: "Low-High", 3: "Low-Low", 4: "High-Low"}
GI_NAMES = {3: "hot 99%", 2: "hot 95%", 1: "hot 90%", 0: "not significant", -1: "cold 90%", -2: "cold 95%", -3: "cold 99%"}
