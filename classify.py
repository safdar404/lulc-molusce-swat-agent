"""Supervised and unsupervised LULC classification (v0.8.0).

* Spectral index library (Sentinel-2 / Landsat presets, reflectance scaling)
* Feature stacks: bands from one multi-band file or separate single-band files, extra layers (DEM, SAR, ...),
  spectral indices and local texture (moving-window standard deviation)
* Classifiers: Random Forest, Extra Trees, Histogram Gradient Boosting (XGBoost-style), SVM (RBF),
  Gaussian Maximum Likelihood, and K-means clustering
* Validation: random stratified k-fold AND spatial block k-fold (Roberts et al. 2017; Ploton et al. 2020) so the
  optimism of random CV with autocorrelated samples is visible; permutation feature importance
* Prediction in row chunks (memory-safe), confidence (max class probability) raster, optional majority filter
"""
import numpy as np
import pandas as pd
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform
from scipy import ndimage

import metrics
from store import to_geotiff_bytes

ROLES = ["blue", "green", "red", "re1", "re2", "re3", "nir", "nir2", "swir1", "swir2"]

# band numbers inside one stacked file, and reflectance = DN * scale + offset
PRESETS = {
    "Sentinel-2 L2A, 10 bands (B2 B3 B4 B5 B6 B7 B8 B8A B11 B12)": dict(
        bands=dict(blue=1, green=2, red=3, re1=4, re2=5, re3=6, nir=7, nir2=8, swir1=9, swir2=10), scale=1e-4, offset=0.0),
    "Sentinel-2 L2A, 4 bands at 10 m (B2 B3 B4 B8)": dict(bands=dict(blue=1, green=2, red=3, nir=4), scale=1e-4, offset=0.0),
    "Landsat 8/9 C2 L2, 7 bands (B1-B7)": dict(bands=dict(blue=2, green=3, red=4, nir=5, swir1=6, swir2=7), scale=2.75e-5, offset=-0.2),
    "Landsat 4/5/7 C2 L2, 6 bands (B1-B5, B7)": dict(bands=dict(blue=1, green=2, red=3, nir=4, swir1=5, swir2=6), scale=2.75e-5, offset=-0.2),
    "Downloaded Landsat composite, 6 bands (blue green red nir swir1 swir2)": dict(
        bands=dict(blue=1, green=2, red=3, nir=4, swir1=5, swir2=6), scale=1e-4, offset=0.0),
    "Already reflectance 0-1 (custom order)": dict(bands={}, scale=1.0, offset=0.0),
}

_e = 1e-6
INDICES = {
    # name: (required roles, function(b) -> array, reference)
    "NDVI": (("nir", "red"), lambda b: (b["nir"] - b["red"]) / (b["nir"] + b["red"] + _e), "Rouse et al. 1974"),
    "EVI": (("nir", "red", "blue"), lambda b: 2.5 * (b["nir"] - b["red"]) / (b["nir"] + 6 * b["red"] - 7.5 * b["blue"] + 1), "Huete et al. 2002"),
    "SAVI": (("nir", "red"), lambda b: 1.5 * (b["nir"] - b["red"]) / (b["nir"] + b["red"] + 0.5), "Huete 1988"),
    "MSAVI": (("nir", "red"), lambda b: (2 * b["nir"] + 1 - np.sqrt(np.maximum((2 * b["nir"] + 1) ** 2 - 8 * (b["nir"] - b["red"]), 0))) / 2, "Qi et al. 1994"),
    "GNDVI": (("nir", "green"), lambda b: (b["nir"] - b["green"]) / (b["nir"] + b["green"] + _e), "Gitelson et al. 1996"),
    "NDWI": (("green", "nir"), lambda b: (b["green"] - b["nir"]) / (b["green"] + b["nir"] + _e), "McFeeters 1996"),
    "MNDWI": (("green", "swir1"), lambda b: (b["green"] - b["swir1"]) / (b["green"] + b["swir1"] + _e), "Xu 2006"),
    "AWEIsh": (("blue", "green", "nir", "swir1", "swir2"), lambda b: b["blue"] + 2.5 * b["green"] - 1.5 * (b["nir"] + b["swir1"]) - 0.25 * b["swir2"], "Feyisa et al. 2014"),
    "NDMI": (("nir", "swir1"), lambda b: (b["nir"] - b["swir1"]) / (b["nir"] + b["swir1"] + _e), "Gao 1996"),
    "NBR": (("nir", "swir2"), lambda b: (b["nir"] - b["swir2"]) / (b["nir"] + b["swir2"] + _e), "Key & Benson 2006"),
    "NDBI": (("swir1", "nir"), lambda b: (b["swir1"] - b["nir"]) / (b["swir1"] + b["nir"] + _e), "Zha et al. 2003"),
    "UI": (("swir2", "nir"), lambda b: (b["swir2"] - b["nir"]) / (b["swir2"] + b["nir"] + _e), "Kawamura et al. 1996"),
    "BSI": (("swir1", "red", "nir", "blue"), lambda b: ((b["swir1"] + b["red"]) - (b["nir"] + b["blue"])) / ((b["swir1"] + b["red"]) + (b["nir"] + b["blue"]) + _e), "Rikimaru et al. 2002"),
    "NDRE": (("nir", "re1"), lambda b: (b["nir"] - b["re1"]) / (b["nir"] + b["re1"] + _e), "Barnes et al. 2000"),
    "CIre": (("nir", "re1"), lambda b: b["nir"] / (b["re1"] + _e) - 1, "Gitelson et al. 2003"),
}


def available_indices(band_map):
    return [k for k, (req, _, _) in INDICES.items() if all(r in band_map for r in req)]


# ---------------------------------------------------------------- feature spec
def _resolve(store, ref):
    """'file.tif' or 'file.tif#3' -> Raster."""
    return store.get(ref)


def build_spec(store, band_map, extra_layers=(), indices=(), texture=False, scale=1.0, offset=0.0):
    """Validate a feature specification and return it with the grid reference."""
    band_map = {k: v for k, v in (band_map or {}).items() if v}
    if not band_map and not extra_layers:
        raise ValueError("Give at least one band (band_map) or extra layer.")
    bad = [r for r in band_map if r not in ROLES]
    if bad:
        raise ValueError(f"Unknown band roles {bad}; use {ROLES}.")
    refs = list(band_map.values()) + list(extra_layers)
    rs = [_resolve(store, r) for r in refs]
    g = rs[0]
    for r, n in zip(rs[1:], refs[1:]):
        if r.data.shape != g.data.shape or r.crs != g.crs or not np.allclose(tuple(r.transform)[:6], tuple(g.transform)[:6]):
            raise ValueError(f"{n} is not on the same grid as {refs[0]}; align all inputs first.")
    indices = [i for i in indices if i in INDICES]
    missing = {i: [r for r in INDICES[i][0] if r not in band_map] for i in indices}
    missing = {k: v for k, v in missing.items() if v}
    if missing:
        raise ValueError(f"Indices need bands that are not mapped: {missing}")
    names = [f"band_{k}" for k in band_map] + [f"layer_{x}" for x in extra_layers] + list(indices)
    if texture:
        tex_src = "nir" if "nir" in band_map else (next(iter(band_map)) if band_map else None)
        if tex_src:
            names.append(f"texture_std5_{tex_src}")
        if "NDVI" in indices:
            names.append("texture_std5_NDVI")
    return dict(band_map=band_map, extra_layers=list(extra_layers), indices=indices, texture=bool(texture),
                scale=float(scale), offset=float(offset), names=names, ref=refs[0], shape=g.data.shape)


def _std(a, size=5):
    m = ndimage.uniform_filter(a, size, mode="nearest")
    m2 = ndimage.uniform_filter(a * a, size, mode="nearest")
    return np.sqrt(np.maximum(m2 - m * m, 0))


def features(store, spec, r0=0, r1=None):
    """Feature cube (n_features, rows, cols) as float32 for rows r0:r1 (with a halo for texture)."""
    H = spec["shape"][0]
    r1 = H if r1 is None else r1
    halo = 2 if spec["texture"] else 0
    a0, a1 = max(0, r0 - halo), min(H, r1 + halo)
    sl = slice(a0, a1)
    b = {k: _resolve(store, v).data[sl].astype("float32") * spec["scale"] + spec["offset"] for k, v in spec["band_map"].items()}
    out = [b[k] for k in spec["band_map"]]
    out += [_resolve(store, x).data[sl].astype("float32") for x in spec["extra_layers"]]
    idx = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for name in spec["indices"]:
            idx[name] = INDICES[name][1](b).astype("float32")
            out.append(idx[name])
    if spec["texture"]:
        src = "nir" if "nir" in b else (next(iter(b)) if b else None)
        if src:
            out.append(_std(b[src]))
        if "NDVI" in idx:
            out.append(_std(np.nan_to_num(idx["NDVI"])))
    cube = np.stack(out).astype("float32")
    return cube[:, r0 - a0: r0 - a0 + (r1 - r0)]


def valid_mask(store, spec):
    refs = list(spec["band_map"].values()) + spec["extra_layers"]
    m = np.zeros(spec["shape"], bool)
    for r in refs:
        m |= _resolve(store, r).mask
    return ~m


def compute_index_rasters(store, band_map, names, scale=1.0, offset=0.0, prefix=""):
    spec = build_spec(store, band_map, (), names, False, scale, offset)
    ok = valid_mask(store, spec)
    g = _resolve(store, spec["ref"])
    cube = features(store, spec)
    nb = len(spec["band_map"])
    res = []
    for i, n in enumerate(spec["indices"]):
        arr = np.where(ok & np.isfinite(cube[nb + i]), cube[nb + i], -9999).astype("float32")
        out = f"{prefix}{n}.tif"
        store.outputs[out] = to_geotiff_bytes(g.profile, arr, "float32", -9999)
        v = arr[arr != -9999]
        res.append(dict(index=n, output=out, reference=INDICES[n][2], min=float(v.min()) if v.size else None,
                        mean=float(v.mean()) if v.size else None, max=float(v.max()) if v.size else None))
    return dict(indices=res, scale=scale, offset=offset,
                note="Indices use surface reflectance (DN x scale + offset). Check the preset matches your product and band order.")


# ---------------------------------------------------------------- training data
def sample_training(store, spec, table, class_col, x_col, y_col, epsg=None, group_col=None):
    g = _resolve(store, spec["ref"])
    df = table.dropna(subset=[class_col, x_col, y_col]).copy()
    xs, ys = df[x_col].astype(float).to_numpy(), df[y_col].astype(float).to_numpy()
    if epsg and g.crs and str(g.crs.to_epsg()) != str(int(epsg)):
        xs, ys = (np.asarray(v) for v in warp_transform(f"EPSG:{int(epsg)}", g.crs, list(xs), list(ys)))
    rows, cols = (np.asarray(v) for v in rowcol(g.transform, xs, ys))
    H, W = spec["shape"]
    ok = (rows >= 0) & (rows < H) & (cols >= 0) & (cols < W)
    grp = df[group_col].to_numpy() if group_col and group_col in df else None
    rows, cols, xs, ys, y = rows[ok], cols[ok], xs[ok], ys[ok], df[class_col].to_numpy()[ok]
    grp = grp[ok] if grp is not None else None
    vm = valid_mask(store, spec)
    keep = vm[rows, cols]
    rows, cols, xs, ys, y = rows[keep], cols[keep], xs[keep], ys[keep], y[keep]
    grp = grp[keep] if grp is not None else None
    X = np.empty((rows.size, len(spec["names"])), "float32")
    order = np.argsort(rows)
    # read features in row chunks to limit memory
    for start in range(0, rows.size, 20000):
        sel = order[start:start + 20000]
        r0, r1 = int(rows[sel].min()), int(rows[sel].max()) + 1
        cube = features(store, spec, r0, r1)
        X[sel] = cube[:, rows[sel] - r0, cols[sel]].T
    fin = np.isfinite(X).all(1)
    try:
        y = y.astype(int)
    except ValueError as e:
        raise ValueError("Class column must contain integer class codes (e.g. 1 = Water).") from e
    dropped = int(len(table) - fin.sum())
    # dedupe points falling in the same pixel (keeps CV honest)
    pix = pd.Series(rows[fin] * W + cols[fin])
    first = ~pix.duplicated().to_numpy()
    out = (X[fin][first], y[fin][first], xs[fin][first], ys[fin][first], dropped + int((~first).sum()))
    if group_col:
        return out + ((grp[fin][first] if grp is not None else None),)
    return out


# ---------------------------------------------------------------- models
MODELS = ["Random Forest", "Extra Trees", "Gradient Boosting (hist)", "SVM (RBF)", "Maximum Likelihood (Gaussian)"]


def make_model(name, seed=42, n_trees=300):
    from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    if name == "Random Forest":
        return RandomForestClassifier(n_estimators=int(n_trees), n_jobs=-1, random_state=seed, class_weight="balanced_subsample", min_samples_leaf=1)
    if name == "Extra Trees":
        return ExtraTreesClassifier(n_estimators=int(n_trees), n_jobs=-1, random_state=seed, class_weight="balanced")
    if name == "Gradient Boosting (hist)":
        return HistGradientBoostingClassifier(max_iter=int(n_trees), learning_rate=0.08, random_state=seed, class_weight="balanced")
    if name == "SVM (RBF)":
        return make_pipeline(StandardScaler(), SVC(C=10, gamma="scale", class_weight="balanced", random_state=seed))
    if name == "Maximum Likelihood (Gaussian)":
        return QuadraticDiscriminantAnalysis(reg_param=1e-3)
    raise ValueError(f"model must be one of {MODELS}")


def _scores(y, p, classes):
    mat, cls = metrics.confusion_matrix(y.tolist(), p.tolist())
    acc = metrics.accuracy_from_matrix(mat)
    pa, ua = np.array(acc["producers_accuracy"], float), np.array(acc["users_accuracy"], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(pa + ua > 0, 2 * pa * ua / (pa + ua), 0)
    return dict(overall_accuracy=acc["overall_accuracy"], kappa=acc["kappa"], macro_f1=float(np.nanmean(f1)), classes=cls,
                producers_accuracy=acc["producers_accuracy"], users_accuracy=acc["users_accuracy"], f1=f1.tolist(),
                confusion_matrix_rows_reference_cols_predicted=mat.tolist())


def cross_validate(model_name, X, y, xs, ys, block_m=1000.0, folds=5, seed=42, n_trees=300, polygon_groups=None):
    from sklearn.base import clone
    from sklearn.model_selection import GroupKFold, StratifiedKFold
    base = make_model(model_name, seed, n_trees)
    out = {}
    counts = pd.Series(y).value_counts()
    kr = int(min(folds, counts.min()))
    if kr >= 2:
        pred = np.empty_like(y)
        for tr, te in StratifiedKFold(kr, shuffle=True, random_state=seed).split(X, y):
            pred[te] = clone(base).fit(X[tr], y[tr]).predict(X[te])
        out["random_kfold"] = dict(folds=kr, **_scores(y, pred, None))
    groups = (np.floor(xs / block_m).astype(np.int64) * 1_000_003 + np.floor(ys / block_m).astype(np.int64))
    ng = len(np.unique(groups))
    ks = int(min(folds, ng))
    if ks >= 2:
        pred = np.empty_like(y)
        for tr, te in GroupKFold(ks).split(X, y, groups):
            if len(np.unique(y[tr])) < 2:
                pred[te] = y[tr][0]
                continue
            pred[te] = clone(base).fit(X[tr], y[tr]).predict(X[te])
        out["spatial_block_kfold"] = dict(folds=ks, block_m=float(block_m), blocks=ng, **_scores(y, pred, None))
    if polygon_groups is not None and len(np.unique(polygon_groups)) >= 2:
        kp = int(min(folds, len(np.unique(polygon_groups))))
        pred = np.empty_like(y)
        for tr, te in GroupKFold(kp).split(X, y, polygon_groups):
            if len(np.unique(y[tr])) < 2:
                pred[te] = y[tr][0]
                continue
            pred[te] = clone(base).fit(X[tr], y[tr]).predict(X[te])
        out["polygon_group_kfold"] = dict(folds=kp, polygons=int(len(np.unique(polygon_groups))), **_scores(y, pred, None))
    if "random_kfold" in out and "spatial_block_kfold" in out:
        out["optimism_gap_oa"] = out["random_kfold"]["overall_accuracy"] - out["spatial_block_kfold"]["overall_accuracy"]
    return out


def importance(model, X, y, names, seed=42):
    from sklearn.inspection import permutation_importance
    n = min(len(y), 3000)
    idx = np.random.default_rng(seed).choice(len(y), n, replace=False)
    r = permutation_importance(model, X[idx], y[idx], n_repeats=5, random_state=seed, n_jobs=1)
    return sorted([dict(feature=f, importance=float(m), std=float(s)) for f, m, s in zip(names, r.importances_mean, r.importances_std)],
                  key=lambda d: -d["importance"])


def majority_filter(cls, valid, size):
    if size < 3:
        return cls
    vals = np.unique(cls[valid])
    best = np.zeros(cls.shape, "float32")
    out = cls.copy()
    for v in vals:
        c = ndimage.uniform_filter(((cls == v) & valid).astype("float32"), size, mode="nearest")
        upd = c > best + 1e-6
        out[upd] = v
        best = np.maximum(best, c)
    return np.where(valid, out, cls)


def predict_raster(store, spec, model, out_name, conf_name=None, chunk_rows=256, smooth=0):
    g = _resolve(store, spec["ref"])
    H, W = spec["shape"]
    ok = valid_mask(store, spec)
    cls = np.zeros((H, W), "int32")
    conf = np.full((H, W), np.nan, "float32") if conf_name and hasattr(model, "predict_proba") else None
    for r0 in range(0, H, chunk_rows):
        r1 = min(H, r0 + chunk_rows)
        cube = features(store, spec, r0, r1).reshape(len(spec["names"]), -1).T
        m = ok[r0:r1].ravel() & np.isfinite(cube).all(1)
        if not m.any():
            continue
        flat = np.zeros((r1 - r0) * W, "int32")
        if conf is not None:
            pr = model.predict_proba(cube[m])
            flat[m] = model.classes_[pr.argmax(1)]
            cf = np.full((r1 - r0) * W, np.nan, "float32")
            cf[m] = pr.max(1)
            conf[r0:r1] = cf.reshape(r1 - r0, W)
        else:
            flat[m] = model.predict(cube[m])
        cls[r0:r1] = flat.reshape(r1 - r0, W)
        ok[r0:r1] &= m.reshape(r1 - r0, W)
    if smooth:
        cls = majority_filter(cls, ok, int(smooth))
    nod = 0 if cls[ok].min(initial=1) > 0 else 65535
    dtype = "uint8" if cls[ok].max(initial=0) < 255 and nod == 0 else "uint16"
    store.outputs[out_name] = to_geotiff_bytes(g.profile, np.where(ok, cls, nod), dtype, nod)
    res = dict(output=out_name, valid_pixels=int(ok.sum()))
    if conf is not None:
        store.outputs[conf_name] = to_geotiff_bytes(g.profile, np.where(ok, conf, -9999), "float32", -9999)
        res.update(confidence_output=conf_name, mean_confidence=float(np.nanmean(conf[ok])),
                   low_confidence_share=float((conf[ok] < 0.5).mean()))
    u, c = np.unique(cls[ok], return_counts=True)
    pa = abs(g.transform.a * g.transform.e) / 1e4 if g.crs is not None and g.crs.is_projected else None
    res["class_pixels"] = {int(k): int(v) for k, v in zip(u, c)}
    if pa:
        res["class_area_ha"] = {int(k): round(float(v) * pa, 2) for k, v in zip(u, c)}
    return res


def kmeans(store, spec, k, out_name, sample=100_000, seed=42):
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    ok = valid_mask(store, spec)
    rr, cc = np.nonzero(ok)
    sel = np.random.default_rng(seed).choice(rr.size, min(sample, rr.size), replace=False)
    rows, cols = rr[sel], cc[sel]
    order = np.argsort(rows)
    X = np.empty((sel.size, len(spec["names"])), "float32")
    for start in range(0, sel.size, 20000):
        s = order[start:start + 20000]
        r0, r1 = int(rows[s].min()), int(rows[s].max()) + 1
        X[s] = features(store, spec, r0, r1)[:, rows[s] - r0, cols[s]].T
    X = X[np.isfinite(X).all(1)]
    model = make_pipeline(StandardScaler(), MiniBatchKMeans(n_clusters=int(k), random_state=seed, n_init=5, batch_size=4096)).fit(X)

    class _Shift:  # clusters numbered 1..k
        def __init__(self, m):
            self.m = m

        def predict(self, Z):
            return self.m.predict(Z) + 1
    res = predict_raster(store, spec, _Shift(model), out_name)
    res["note"] = "K-means clusters are spectral groups, not land-cover classes: label them by inspection before using them as a map."
    return res


# ---------------------------------------------------------------- high-level entry points (UI + agent)
def preset_band_map(store, stack, preset):
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {list(PRESETS)}")
    n = store.band_count(stack)
    bm = PRESETS[preset]["bands"]
    if not bm:
        raise ValueError("This preset has no band order; give band_map explicitly.")
    if max(bm.values()) > n:
        raise ValueError(f"{stack} has {n} band(s) but the preset needs {max(bm.values())}. Pick another preset or map bands manually.")
    return {k: f"{stack}#{v}" for k, v in bm.items()}, PRESETS[preset]["scale"], PRESETS[preset]["offset"]


def train_and_predict(store, models_cache, table, class_col, x_col, y_col, band_map=None, stack=None, preset=None, extra_layers=(),
                      indices=("NDVI",), texture=False, scale=None, offset=None, model="Random Forest", n_trees=300, block_m=1000.0,
                      folds=5, epsg=None, predict=True, output_name="classified.tif", smooth=0, labels=None, seed=42):
    s0, o0 = 1.0, 0.0
    if stack and preset:
        bm, s0, o0 = preset_band_map(store, stack, preset)
        band_map = {**bm, **(band_map or {})}
    spec = build_spec(store, band_map or {}, extra_layers, indices, texture, s0 if scale is None else scale, o0 if offset is None else offset)
    gcol = "polygon_id" if "polygon_id" in table.columns else None
    X, y, xs, ys, dropped, groups = sample_training(store, spec, table, class_col, x_col, y_col, epsg, group_col=gcol or "__none__")
    counts = pd.Series(y).value_counts().sort_index()
    if len(counts) < 2:
        raise ValueError("Training data need at least two classes inside the image.")
    if counts.min() < 5:
        raise ValueError(f"Too few training pixels for classes {counts[counts < 5].index.tolist()} (need ≥ 5, ideally ≥ 50).")
    warnings = []
    if counts.min() < 30:
        warnings.append(f"Classes {counts[counts < 30].index.tolist()} have < 30 training pixels; results for them are unreliable.")
    if counts.max() / counts.min() > 10:
        warnings.append("Training classes are strongly imbalanced (>10:1); class-balanced weighting is used but check user's accuracy of rare classes.")
    cv = cross_validate(model, X, y, xs, ys, block_m, folds, seed, n_trees, polygon_groups=groups)
    final = make_model(model, seed, n_trees).fit(X, y)
    key = output_name.rsplit(".", 1)[0]
    models_cache[key] = dict(model=final, spec=spec, model_name=model)
    out = dict(model=model, model_key=key, features=spec["names"], training_pixels=int(len(y)), points_dropped=dropped,
               per_class_training={f"{k} {(labels or {}).get(str(k), '')}".strip(): int(v) for k, v in counts.items()},
               cross_validation=cv, feature_importance=importance(final, X, y, spec["names"], seed)[:20], warnings=warnings)
    if predict:
        out["prediction"] = predict_raster(store, spec, final, output_name, f"{key}_confidence.tif", smooth=int(smooth))
    out["note"] = ("Report the spatial-block CV accuracy, not the random-CV figure: random k-fold is optimistic when training points are "
                   "clustered. Then validate the map with independent stratified random points in the Area-adjusted accuracy tab.")
    return out
