"""Landscape pattern metrics for categorical LULC rasters (FRAGSTATS definitions; McGarigal et al. 2023).

Class level   : CA, PLAND, NP, PD, LPI, TE, ED, LSI, AREA_MN/AM/CV, SHAPE_MN/AM, FRAC_MN, ENN_MN, TCA, CPLAND,
                CLUMPY-free AI, COHESION, DIVISION, MESH, SPLIT
Landscape     : TA, NP, PD, LPI, TE, ED, LSI, AREA_MN, SHAPE_MN, FRAC_MN, ENN_MN, CONTAG, SHDI, SHEI, SIDI, SIEI,
                PR, PRD, AI, DIVISION, MESH, SPLIT, COHESION
Moving window : SHDI, SIDI, PR, ED or PLAND of one class, as a raster

Conventions (FRAGSTATS defaults): 8-neighbour patch rule (4 optional); total edge excludes the landscape boundary
and NoData; LSI counts the boundary as edge; shape and LSI use the raster (cell-count) square standard; ENN is the
cell-centre to cell-centre distance between the closest cells of two patches of the same class.
"""
import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.spatial import cKDTree

STRUCT = {8: np.ones((3, 3), bool), 4: ndimage.generate_binary_structure(2, 1)}


def _min_perimeter(n):
    """Minimum perimeter (cell edges) of a patch of n cells (FRAGSTATS raster square standard)."""
    n = np.asarray(n, float)
    m = np.floor(np.sqrt(n))
    return np.where(n == m * m, 4 * m, np.where(n <= m * (m + 1), 4 * m + 2, 4 * m + 4))


def _max_like_adjacencies(n):
    """Maximum like adjacencies (single count) of n cells (He et al. 2000, aggregation index)."""
    n = np.asarray(n, float)
    m = np.floor(np.sqrt(n))
    r = n - m * m
    return np.where(r == 0, 2 * m * (m - 1), np.where(r <= m, 2 * m * (m - 1) + 2 * r - 1, 2 * m * (m - 1) + 2 * r - 2))


def _adjacency(idx, valid, k):
    """Single-count adjacency matrix G[i, j] over 4-neighbour cell edges, and boundary edges per class."""
    G = np.zeros((k, k))
    for a, b, va, vb in ((idx[:, :-1], idx[:, 1:], valid[:, :-1], valid[:, 1:]),
                         (idx[:-1, :], idx[1:, :], valid[:-1, :], valid[1:, :])):
        ok = va & vb
        G += np.bincount(a[ok] * k + b[ok], minlength=k * k).reshape(k, k)
    pad = np.pad(valid, 1, constant_values=False)
    nb_invalid = (~pad[:-2, 1:-1]).astype(int) + ~pad[2:, 1:-1] + ~pad[1:-1, :-2] + ~pad[1:-1, 2:]
    boundary = np.bincount(idx[valid], weights=nb_invalid[valid], minlength=k)
    return G, boundary


def _enn(labels, n_patches, struct, res, max_patches=20000, max_points=3_000_000):
    """Nearest-neighbour distance (m) for each patch label 1..n of one class."""
    out = np.full(n_patches, np.nan)
    if n_patches < 2 or n_patches > max_patches:
        return out
    mask = labels > 0
    edge = mask & ~ndimage.binary_erosion(mask, struct, border_value=0)
    rr, cc = np.nonzero(edge)
    if rr.size > max_points:
        return out
    lab = labels[rr, cc]
    pts = np.column_stack([rr, cc]).astype(float)
    tree = cKDTree(pts)
    best = np.full(len(pts), np.inf)
    pbest = np.full(n_patches + 1, np.inf)          # best distance found so far per patch
    todo = np.arange(len(pts))
    k = 8
    while todo.size:
        kk = min(k, len(pts))
        d, j = tree.query(pts[todo], k=kk, workers=-1)
        dd = np.where(lab[j] != lab[todo][:, None], d, np.inf).min(axis=1)
        best[todo] = dd
        np.minimum.at(pbest, lab[todo], dd)
        # still open: no other patch among the k neighbours AND an unseen neighbour could beat the patch's best
        todo = todo[np.isinf(dd) & (d[:, -1] < pbest[lab[todo]])]
        if kk == len(pts) or k >= 512:
            break
        k *= 2
    for L in np.unique(lab[todo]):  # exact fallback for the few patches still open
        own = lab == L
        best[own] = cKDTree(pts[~own]).query(pts[own], k=1)[0]
    np.minimum.at(pbest, lab, best)
    out[:] = np.where(np.isfinite(pbest[1:]), pbest[1:] * res, np.nan)
    return out


def _cv(x):
    return float(np.std(x) / np.mean(x) * 100) if len(x) and np.mean(x) else np.nan


def compute(data, valid, res, neighbourhood=8, edge_depth_cells=1, labels=None, with_patches=False, with_enn=True):
    """All class- and landscape-level metrics for one categorical array. res = cell size (m)."""
    if neighbourhood not in STRUCT:
        raise ValueError("neighbourhood must be 4 or 8")
    struct = STRUCT[neighbourhood]
    vals = data[valid].astype(np.int64)
    classes = np.unique(vals)
    k = len(classes)
    if k == 0:
        raise ValueError("No valid cells.")
    idx = np.zeros(data.shape, np.int64)
    idx[valid] = np.searchsorted(classes, vals)
    cell_ha = res * res / 1e4
    Z = int(valid.sum())
    TA = Z * cell_ha
    G, boundary = _adjacency(idx, valid, k)
    Gs = G + G.T                                # symmetric; diagonal = 2 × like adjacencies
    like = np.diag(G).copy()
    unlike_edges = Gs.sum(1) - np.diag(Gs)      # edges of class i shared with other classes
    counts = np.bincount(idx[valid], minlength=k).astype(float)
    P = counts / Z

    rows, patches = [], []
    all_area, all_perim, all_shape, all_frac, all_enn = [], [], [], [], []
    for i, c in enumerate(classes):
        m = valid & (idx == i)
        lab, n = ndimage.label(m, struct)
        a_cells = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype(float)
        # patch perimeter = 4-neighbour edges facing any other value (incl. NoData and landscape boundary)
        pad = np.pad(m, 1, constant_values=False)
        nb_out = (~pad[:-2, 1:-1]).astype(int) + ~pad[2:, 1:-1] + ~pad[1:-1, :-2] + ~pad[1:-1, 2:]
        p_cells = np.bincount(lab[m], weights=nb_out[m], minlength=n + 1)[1:]
        a_m2, p_m = a_cells * res * res, p_cells * res
        shape = p_cells / _min_perimeter(a_cells)
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(a_cells > 1, 2 * np.log(0.25 * p_m) / np.log(a_m2), 1.0)
        enn = _enn(lab, n, struct, res) if with_enn else np.full(n, np.nan)
        if edge_depth_cells and edge_depth_cells > 0:
            # FRAGSTATS / landscapemetrics: 4-neighbour erosion; landscape boundary and NoData count as edge
            dist = ndimage.distance_transform_cdt(np.pad(m, 1, constant_values=False), "taxicab")[1:-1, 1:-1]
            core = m & (dist > edge_depth_cells)
        else:
            core = m
        tca = core.sum() * cell_ha
        a_ha = a_cells * cell_ha
        ai = like[i] / _max_like_adjacencies(counts[i]) * 100 if _max_like_adjacencies(counts[i]) > 0 else np.nan
        coh = (1 - p_cells.sum() / (p_cells * np.sqrt(a_cells)).sum()) / (1 - 1 / np.sqrt(Z)) * 100 if Z > 1 else np.nan
        div = 1 - np.sum((a_cells / Z) ** 2)
        mesh = np.sum(a_cells ** 2) / Z * cell_ha
        name = f"{c} {(labels or {}).get(str(c), '')}".strip()
        rows.append(dict(
            class_code=int(c), class_name=name, CA_ha=counts[i] * cell_ha, PLAND=P[i] * 100, NP=n, PD=n / TA * 100,
            LPI=a_cells.max() / Z * 100 if n else 0.0, TE_m=unlike_edges[i] * res, ED_m_per_ha=unlike_edges[i] * res / TA,
            LSI=(unlike_edges[i] + boundary[i]) / _min_perimeter(counts[i]),
            AREA_MN_ha=a_ha.mean() if n else np.nan, AREA_AM_ha=float((a_ha * a_ha).sum() / a_ha.sum()) if n else np.nan,
            AREA_CV=_cv(a_ha), SHAPE_MN=shape.mean() if n else np.nan, SHAPE_AM=float((shape * a_cells).sum() / a_cells.sum()) if n else np.nan,
            FRAC_MN=np.nanmean(frac) if n else np.nan, ENN_MN_m=np.nanmean(enn) if np.isfinite(enn).any() else np.nan,
            TCA_ha=tca, CPLAND=tca / TA * 100, AI=ai, COHESION=coh, DIVISION=div, MESH_ha=mesh, SPLIT=Z * Z / np.sum(a_cells ** 2)))
        all_area.append(a_cells)
        all_perim.append(p_cells)
        all_shape.append(shape)
        all_frac.append(frac)
        all_enn.append(enn)
        if with_patches:
            patches.append(pd.DataFrame(dict(class_code=int(c), patch=np.arange(1, n + 1), area_ha=a_ha, perimeter_m=p_m,
                                             SHAPE=shape, FRAC=frac, ENN_m=enn)))
    cls = pd.DataFrame(rows)

    A, Pm = np.concatenate(all_area), np.concatenate(all_perim)
    S, F, E = np.concatenate(all_shape), np.concatenate(all_frac), np.concatenate(all_enn)
    TE_cells = unlike_edges.sum() / 2
    # contagion from double-counted adjacencies including like adjacencies (FRAGSTATS CONTAG)
    with np.errstate(divide="ignore", invalid="ignore"):
        rowsum = Gs.sum(1, keepdims=True)
        q = P[:, None] * np.where(rowsum > 0, Gs / rowsum, 0)
        ent = np.nansum(np.where(q > 0, q * np.log(q), 0))
    contag = (1 + ent / (2 * np.log(k))) * 100 if k > 1 else np.nan
    shdi = -np.sum(P * np.log(P))
    sidi = 1 - np.sum(P * P)
    maxg = _max_like_adjacencies(counts)
    land = dict(
        TA_ha=TA, NP=int(A.size), PD=A.size / TA * 100, LPI=A.max() / Z * 100, TE_m=TE_cells * res, ED_m_per_ha=TE_cells * res / TA,
        LSI=(TE_cells + boundary.sum()) / _min_perimeter(Z), AREA_MN_ha=A.mean() * cell_ha, AREA_CV=_cv(A * cell_ha),
        SHAPE_MN=S.mean(), FRAC_MN=np.nanmean(F), ENN_MN_m=np.nanmean(E) if np.isfinite(E).any() else np.nan,
        CONTAG=contag, SHDI=shdi, SHEI=shdi / np.log(k) if k > 1 else np.nan, SIDI=sidi, SIEI=sidi / (1 - 1 / k) if k > 1 else np.nan,
        PR=k, PRD=k / TA * 100, AI=float(np.nansum(np.where(maxg > 0, like / np.where(maxg > 0, maxg, 1), 0) * P) * 100),
        DIVISION=1 - np.sum((A / Z) ** 2), MESH_ha=np.sum(A ** 2) / Z * cell_ha, SPLIT=Z * Z / np.sum(A ** 2),
        COHESION=(1 - Pm.sum() / (Pm * np.sqrt(A)).sum()) / (1 - 1 / np.sqrt(Z)) * 100 if Z > 1 else np.nan)
    out = dict(classes=cls, landscape=land)
    if with_patches:
        out["patches"] = pd.concat(patches, ignore_index=True)
    return out


# ------------------------------------------------------------------ moving window
WINDOW_METRICS = ("SHDI", "SIDI", "PR", "ED", "PLAND")


def moving_window(data, valid, res, metric, window_m, class_code=None, min_valid=0.5):
    """Square moving window (side = window_m). Returns float32 array (NaN outside valid / sparse windows)."""
    metric = metric.upper()
    if metric not in WINDOW_METRICS:
        raise ValueError(f"metric must be one of {WINDOW_METRICS}")
    size = max(3, int(round(window_m / res)) | 1)  # odd number of cells
    vf = valid.astype("float32")
    nvalid = ndimage.uniform_filter(vf, size, mode="constant")
    ok = valid & (nvalid >= min_valid)
    classes = np.unique(data[valid])
    if metric == "PLAND":
        if class_code is None:
            raise ValueError("PLAND needs class_code")
        share = ndimage.uniform_filter(((data == class_code) & valid).astype("float32"), size, mode="constant")
        out = share / np.maximum(nvalid, 1e-9) * 100
    elif metric == "ED":
        e = np.zeros(data.shape, "float32")
        for a, b in (((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
                     ((slice(None, -1), slice(None)), (slice(1, None), slice(None)))):
            diff = (data[a] != data[b]) & valid[a] & valid[b]
            e[a] += 0.5 * diff
            e[b] += 0.5 * diff
        edges = ndimage.uniform_filter(e, size, mode="constant") * size * size  # edges (cells) in window
        area_ha = nvalid * size * size * res * res / 1e4
        out = edges * res / np.maximum(area_ha, 1e-9)
    else:
        acc = np.zeros(data.shape, "float32")
        for c in classes:
            p = ndimage.uniform_filter(((data == c) & valid).astype("float32"), size, mode="constant") / np.maximum(nvalid, 1e-9)
            p = np.clip(p, 0, 1)
            if metric == "SHDI":
                acc -= np.where(p > 1e-7, p * np.log(np.maximum(p, 1e-7)), 0)
            elif metric == "SIDI":
                acc += p * p
            else:  # PR
                acc += (p > 1e-6)
        out = 1 - acc if metric == "SIDI" else acc
    out = out.astype("float32")
    out[~ok] = np.nan
    return out, size
