"""Driver analysis, transition-potential modelling, Markov-CA scenario simulation and hindcast validation (v0.9.0).

Workflow (same logic as MOLUSCE / Land Change Modeler / CA-Markov, made explicit and auditable):
1. Driver layers: distance to a class of the base map (dynamic: recomputed from each base map), distance to non-zero cells of a
   layer (roads, rivers, towns), slope from a DEM (Horn 1981), or any continuous layer (population, DEM).
2. Driver screening per transition i->j: Cramér's V on deciles, univariate AUC, Pearson correlation and VIF between drivers.
3. Transition potential: logistic regression, Random Forest or a multilayer perceptron (ANN, as in MOLUSCE), trained on a balanced
   sample of pixels that were class i at t0 (changed to j vs persisted); hold-out AUC.
4. Quantity: Markov matrix from the calibration interval, raised to the (fractional) power target_interval / calibration_interval.
   Scenario multipliers, forbidden transitions and a protected-area mask modify the demand.
5. Allocation: iterative cellular automaton. Each iteration allocates a share of the remaining demand of every transition to the
   highest-scoring pixels, score = potential x ((1 - w) + w x share of class j in the neighbourhood) x optional stochastic term.
6. Validation against an observed map: figure of merit with hits / misses / wrong hits / false alarms (Pontius et al. 2008), Kappa
   simulation (van Vliet et al. 2011), quantity / allocation disagreement, and comparison with the null (persistence) model and any
   other simulated maps (e.g. MOLUSCE output).
"""
import math

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.linalg import fractional_matrix_power

import metrics
from rasterops import _projected_metres
from store import to_geotiff_bytes

POTENTIAL_MODELS = ["Logistic regression", "Random Forest", "ANN (MLP)"]
SCENARIOS = {
    "Business as usual": dict(gain=1.0, loss_natural=1.0, protect=False),
    "Ecological protection": dict(gain=0.6, loss_natural=0.5, protect=True),
    "Development priority": dict(gain=1.5, loss_natural=1.2, protect=False),
}


# ------------------------------------------------------------------ helpers
def _grid(store, names):
    rs = [store.get(n) for n in names]
    g = rs[0]
    _projected_metres(g)
    for r, n in zip(rs[1:], names[1:]):
        if r.data.shape != g.data.shape or r.crs != g.crs or not np.allclose(tuple(r.transform)[:6], tuple(g.transform)[:6]):
            raise ValueError(f"{n} is not on the same grid as {names[0]}; align the rasters first (geometry check).")
    return rs


def _res(r):
    return abs(r.transform.a) * (r.crs.linear_units_factor[1] if r.crs.linear_units_factor else 1.0)


def _cat(r):
    return r.data.astype(np.int64)


# ------------------------------------------------------------------ drivers
def distance_to(mask, res):
    """Euclidean distance (m) from every cell to the nearest True cell."""
    if not mask.any():
        return np.full(mask.shape, np.nan, "float32")
    return ndimage.distance_transform_edt(~mask, sampling=res).astype("float32")


def slope_deg(dem, res):
    """Horn (1981) slope in degrees."""
    z = np.pad(dem.astype("float64"), 1, mode="edge")
    dzdx = ((z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:]) - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])) / (8 * res)
    dzdy = ((z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:]) - (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])) / (8 * res)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype("float32")


def driver_name(d):
    t = d["type"]
    if t == "distance_to_class":
        return f"dist_class_{d['class']}"
    if t == "distance_to_layer":
        return f"dist_{d['name'].rsplit('.', 1)[0]}"
    if t == "slope":
        return f"slope_{d['name'].rsplit('.', 1)[0]}"
    return d["name"].rsplit(".", 1)[0]


def driver_stack(store, drivers, base_map, res):
    """(n_drivers, rows, cols) float32. distance_to_class is computed from base_map (dynamic)."""
    out = []
    for d in drivers:
        t = d.get("type")
        if t == "distance_to_class":
            out.append(distance_to(base_map == int(d["class"]), res))
        elif t == "distance_to_layer":
            r = store.get(d["name"])
            out.append(distance_to((r.data != 0) & ~r.mask, res))
        elif t == "slope":
            r = store.get(d["name"])
            out.append(slope_deg(np.where(r.mask, np.nanmean(r.data[~r.mask]), r.data), res))
        elif t == "layer":
            r = store.get(d["name"])
            a = r.data.astype("float32")
            a[r.mask] = np.nan
            out.append(a)
        else:
            raise ValueError(f"Unknown driver type {t}; use distance_to_class, distance_to_layer, slope or layer.")
    return np.stack(out) if out else np.zeros((0,) + base_map.shape, "float32")


def cramers_v(x, y, bins=10):
    """Cramér's V between a continuous driver (binned in quantiles) and a binary/categorical outcome."""
    ok = np.isfinite(x)
    x, y = x[ok], y[ok]
    if x.size < 20 or np.unique(y).size < 2:
        return np.nan
    edges = np.unique(np.quantile(x, np.linspace(0, 1, bins + 1)))
    xb = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, max(len(edges) - 2, 0))
    tab = pd.crosstab(xb, y).to_numpy().astype(float)
    if tab.shape[0] < 2:
        return 0.0
    exp = tab.sum(1, keepdims=True) * tab.sum(0, keepdims=True) / tab.sum()
    chi2 = ((tab - exp) ** 2 / np.where(exp > 0, exp, 1)).sum()
    return float(math.sqrt(chi2 / (tab.sum() * (min(tab.shape) - 1))))


def _auc(score, y):
    from sklearn.metrics import roc_auc_score
    ok = np.isfinite(score)
    if np.unique(y[ok]).size < 2:
        return np.nan
    a = roc_auc_score(y[ok], score[ok])
    return float(max(a, 1 - a))  # direction-free discriminative power


def vif(X):
    """Variance inflation factor of each column."""
    X = X[np.isfinite(X).all(1)]
    out = []
    for j in range(X.shape[1]):
        y, Z = X[:, j], np.delete(X, j, axis=1)
        if Z.shape[1] == 0 or y.std() == 0:
            out.append(1.0 if y.std() else np.nan)
            continue
        Z1 = np.column_stack([np.ones(len(y)), Z])
        beta, *_ = np.linalg.lstsq(Z1, y, rcond=None)
        r2 = 1 - ((y - Z1 @ beta) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        out.append(float(1 / max(1 - r2, 1e-9)))
    return out


# ------------------------------------------------------------------ transitions & sampling
def transition_counts(a, b, valid):
    cls = np.unique(np.concatenate([a[valid], b[valid]]))
    k = len(cls)
    ia, ib = np.searchsorted(cls, a[valid]), np.searchsorted(cls, b[valid])
    return np.bincount(ia * k + ib, minlength=k * k).reshape(k, k).astype(float), cls


def top_transitions(M, cls, n=6, min_pixels=50):
    rows = [(int(cls[i]), int(cls[j]), float(M[i, j])) for i in range(len(cls)) for j in range(len(cls)) if i != j and M[i, j] >= min_pixels]
    rows.sort(key=lambda r: -r[2])
    return rows[:n]


def _balanced_sample(idx_change, idx_stay, n_max, rng):
    n = int(min(len(idx_change), len(idx_stay), n_max // 2))
    if n < 10:
        return None
    return np.concatenate([rng.choice(idx_change, n, replace=False), rng.choice(idx_stay, n, replace=False)]), n


def make_potential_model(name, seed=42):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if name == "Logistic regression":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500))
    if name == "Random Forest":
        return RandomForestClassifier(n_estimators=150, min_samples_leaf=5, n_jobs=-1, random_state=seed)
    if name == "ANN (MLP)":
        return make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(12,), max_iter=600, early_stopping=True, random_state=seed))
    raise ValueError(f"model must be one of {POTENTIAL_MODELS}")


def screen_drivers(a0, a1, valid, D, names, transitions, n_sample=20000, seed=42):
    """Cramér's V and AUC of each driver for each transition, plus VIF across drivers."""
    rng = np.random.default_rng(seed)
    rows = []
    flatD = D.reshape(D.shape[0], -1)
    for i, j, _ in transitions:
        cand = np.flatnonzero((a0 == i).ravel() & valid.ravel())
        ch = cand[(a1.ravel()[cand] == j)]
        st = cand[(a1.ravel()[cand] == i)]
        s = _balanced_sample(ch, st, n_sample, rng)
        if s is None:
            continue
        idx, n = s
        y = np.r_[np.ones(n), np.zeros(n)]
        for k, nm in enumerate(names):
            x = flatD[k, idx]
            rows.append(dict(transition=f"{i}->{j}", driver=nm, cramers_v=cramers_v(x, y), auc=_auc(x, y)))
    sample = flatD[:, rng.choice(np.flatnonzero(valid.ravel()), min(20000, int(valid.sum())), replace=False)].T
    v = vif(sample) if len(names) else []
    corr = pd.DataFrame(sample, columns=names).corr().round(3) if len(names) > 1 else pd.DataFrame()
    return pd.DataFrame(rows), dict(zip(names, v)), corr


def fit_potentials(a0, a1, valid, D, transitions, model_name, n_sample=20000, seed=42):
    """Train one model per transition on pixels that were i at t0. Returns {(i,j): model}, AUC table."""
    from sklearn.base import clone
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(seed)
    flatD = D.reshape(D.shape[0], -1)
    models, rows = {}, []
    base = make_potential_model(model_name, seed)
    for i, j, cnt in transitions:
        cand = np.flatnonzero((a0 == i).ravel() & valid.ravel())
        ch, st = cand[a1.ravel()[cand] == j], cand[a1.ravel()[cand] == i]
        s = _balanced_sample(ch, st, n_sample, rng)
        if s is None:
            rows.append(dict(transition=f"{i}->{j}", pixels=int(cnt), auc_holdout=np.nan, note="too few samples"))
            continue
        idx, n = s
        X = np.nan_to_num(flatD[:, idx].T, nan=0.0)
        y = np.r_[np.ones(n), np.zeros(n)]
        perm = rng.permutation(len(y))
        cut = int(0.7 * len(y))
        tr, te = perm[:cut], perm[cut:]
        m = clone(base).fit(X[tr], y[tr])
        auc = roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]) if np.unique(y[te]).size == 2 else np.nan
        models[(i, j)] = clone(base).fit(X, y)
        rows.append(dict(transition=f"{i}->{j}", pixels=int(cnt), training_pairs=int(n), auc_holdout=float(auc)))
    return models, pd.DataFrame(rows)


# ------------------------------------------------------------------ quantity
def markov_matrix(M, cls, years_calib, years_target):
    P = M / np.where(M.sum(1, keepdims=True) > 0, M.sum(1, keepdims=True), 1)
    for i in range(len(cls)):
        if M[i].sum() == 0:
            P[i, i] = 1.0
    t = years_target / years_calib
    Q = P if np.isclose(t, 1) else np.real(fractional_matrix_power(P, t))
    Q = np.clip(Q, 0, None)
    Q = Q / Q.sum(1, keepdims=True)
    return Q


# ------------------------------------------------------------------ allocation
def allocate(start, valid, candidates_potential, demand, neighbourhood=3, weight=0.5, iterations=10, protected=None,
             stochastic=0.0, seed=42):
    """Iterative CA allocation. candidates_potential: {(i,j): (flat_idx, potential)}; demand: {(i,j): pixels}."""
    rng = np.random.default_rng(seed)
    cur = start.copy()
    flat = cur.ravel()
    changed = np.zeros(flat.size, bool)
    if protected is not None:
        changed |= protected.ravel()
    remaining = {k: int(round(v)) for k, v in demand.items()}
    order = sorted(remaining, key=lambda k: -remaining[k])
    targets = sorted({j for _, j in order})
    vf = valid.astype("float32")
    nvalid = ndimage.uniform_filter(vf, neighbourhood, mode="constant")
    for it in range(iterations):
        left = iterations - it
        share = {j: ndimage.uniform_filter(((cur == j) & valid).astype("float32"), neighbourhood, mode="constant").ravel()
                 / np.maximum(nvalid.ravel(), 1e-6) for j in targets}
        for key in order:
            need = remaining[key]
            if need <= 0:
                continue
            i, j = key
            idx, pot = candidates_potential[key]
            ok = (flat[idx] == i) & ~changed[idx]
            if not ok.any():
                continue
            ci, cp = idx[ok], pot[ok]
            score = cp * ((1 - weight) + weight * share[j][ci])
            if stochastic > 0:
                score = score * (1 + stochastic * (rng.random(score.size) - 0.5))
            q = int(math.ceil(need / left))
            q = min(q, ci.size)
            pick = ci[np.argpartition(-score, q - 1)[:q]] if q < ci.size else ci
            flat[pick] = j
            changed[pick] = True
            remaining[key] -= pick.size
    return cur, {f"{i}->{j}": int(v) for (i, j), v in remaining.items()}


# ------------------------------------------------------------------ validation
def kappa_simulation(initial, observed, simulated):
    """van Vliet et al. (2011) Kappa Simulation: agreement on transitions beyond a random allocation of the same quantities."""
    i, o, s = (np.asarray(x).ravel() for x in (initial, observed, simulated))
    po = (o == s).mean()
    pe = 0.0
    for c in np.unique(i):
        m = i == c
        pc = m.mean()
        oc = pd.Series(o[m]).value_counts(normalize=True)
        sc = pd.Series(s[m]).value_counts(normalize=True)
        pe += pc * float((oc * sc.reindex(oc.index).fillna(0)).sum())
    return float((po - pe) / (1 - pe)) if pe < 1 else float("nan")


def compare(initial, observed, simulated):
    m, _ = metrics.confusion_matrix(observed, simulated)
    acc = metrics.accuracy_from_matrix(m)
    fom = metrics.figure_of_merit(initial, observed, simulated)
    d = metrics.pontius_disagreement(m)
    oc = observed != initial
    sc = simulated != initial
    return dict(overall_agreement=acc["overall_accuracy"], kappa=acc["kappa"], kappa_simulation=kappa_simulation(initial, observed, simulated),
                fom=fom["fom"], hits=fom["hits"], misses=fom["misses"], wrong_hits=fom["wrong_hits"], false_alarms=fom["false_alarms"],
                producers_change=fom["hits"] / max(int(oc.sum()), 1), users_change=fom["hits"] / max(int(sc.sum()), 1),
                quantity_disagreement=d["quantity"], allocation_disagreement=d["allocation"],
                observed_change_pct=float(oc.mean() * 100), simulated_change_pct=float(sc.mean() * 100))


# ------------------------------------------------------------------ store-level entry points
def _drivers_or_default(drivers, classes):
    return drivers or [dict(type="distance_to_class", **{"class": int(c)}) for c in classes]


def driver_analysis(store, map_from, map_to, drivers=None, n_transitions=6, min_pixels=50):
    r0, r1 = _grid(store, [map_from, map_to])
    if drivers:
        _grid(store, [map_from] + [d["name"] for d in drivers if "name" in d])
    valid = ~(r0.mask | r1.mask)
    a0, a1 = _cat(r0), _cat(r1)
    M, cls = transition_counts(a0, a1, valid)
    tr = top_transitions(M, cls, n_transitions, min_pixels)
    if not tr:
        raise ValueError("No transition reaches the minimum pixel count.")
    drivers = _drivers_or_default(drivers, sorted({j for _, j, _ in tr}))
    D = driver_stack(store, drivers, a0, _res(r0))
    names = [driver_name(d) for d in drivers]
    tab, v, corr = screen_drivers(a0, a1, valid, D, names, tr)
    return dict(transitions=[dict(transition=f"{i}->{j}", pixels=int(c)) for i, j, c in tr], drivers=names,
                screening=tab.round(4).to_dict(orient="records"), vif={k: round(x, 2) for k, x in v.items()},
                correlation=corr.reset_index().rename(columns={"index": "driver"}).to_dict(orient="records"),
                note="Cramér's V > 0.15 and AUC > 0.6 suggest a useful driver (MOLUSCE / IDRISI guidance). Drop one of any pair with |r| > 0.8 "
                     "or VIF > 5 to avoid multicollinearity.")


def simulate(store, map_from, map_to, year_from, year_to, year_target, start_map=None, drivers=None, model="Logistic regression",
             n_transitions=6, min_pixels=50, scenario="Business as usual", growth_classes=(), natural_classes=(), multipliers=None,
             forbidden=(), protected_layer=None, apply_protection=None, neighbourhood=3, weight=0.5, iterations=10, stochastic=0.0,
             output_name="simulated.tif", potential_prefix=None, start_year=None, seed=42):
    """Calibrate on map_from->map_to and simulate year_target from start_map (default map_to)."""
    start_map = start_map or map_to
    names_needed = [map_from, map_to, start_map] + ([protected_layer] if protected_layer else []) + [d["name"] for d in (drivers or []) if "name" in d]
    _grid(store, list(dict.fromkeys(names_needed)))
    r0, r1, rs_ = store.get(map_from), store.get(map_to), store.get(start_map)
    valid = ~(r0.mask | r1.mask | rs_.mask)
    a0, a1, start = _cat(r0), _cat(r1), _cat(rs_)
    res = _res(r0)
    if not year_from < year_to:
        raise ValueError("year_from must be earlier than year_to.")
    start_year = year_to if start_year is None else start_year
    M, cls = transition_counts(a0, a1, valid)
    tr = top_transitions(M, cls, n_transitions, min_pixels)
    if not tr:
        raise ValueError("No transition reaches the minimum pixel count in the calibration interval.")
    drivers = _drivers_or_default(drivers, sorted({j for _, j, _ in tr}))
    D0 = driver_stack(store, drivers, a0, res)
    models, auc = fit_potentials(a0, a1, valid, D0, tr, model, seed=seed)
    if not models:
        raise ValueError("No transition had enough samples to train a potential model.")

    # quantity
    years_target = year_target - start_year
    if years_target <= 0:
        raise ValueError("Target year must be after the start map's year.")
    Q = markov_matrix(M, cls, year_to - year_from, years_target)
    start_counts = {int(c): int(((start == c) & valid).sum()) for c in cls}
    sc = SCENARIOS.get(scenario, SCENARIOS["Business as usual"])
    mult = dict(multipliers or {})
    forb = {x if isinstance(x, str) else f"{int(x[0])}->{int(x[1])}" for x in (forbidden or ())}
    forb = {x.replace(" ", "") for x in forb}
    demand = {}
    for (i, j) in models:
        d = start_counts.get(i, 0) * Q[list(cls).index(i), list(cls).index(j)]
        f = float(mult.get(f"{i}->{j}", 1.0))
        if j in [int(x) for x in growth_classes]:
            f *= sc["gain"]
        if i in [int(x) for x in natural_classes]:
            f *= sc["loss_natural"]
        if f"{i}->{j}" in forb:
            f = 0.0
        demand[(i, j)] = d * f
    protected = None
    if protected_layer and (sc["protect"] if apply_protection is None else apply_protection):
        pr = store.get(protected_layer)
        protected = (pr.data != 0) & ~pr.mask

    # potentials on the start map (dynamic distance drivers recomputed from the start map)
    Ds = driver_stack(store, drivers, start, res).reshape(len(drivers), -1)
    cand = {}
    for (i, j), m in models.items():
        idx = np.flatnonzero((start == i).ravel() & valid.ravel())
        pot = np.zeros(idx.size, "float32")
        for s in range(0, idx.size, 500_000):
            sl = idx[s:s + 500_000]
            pot[s:s + sl.size] = m.predict_proba(np.nan_to_num(Ds[:, sl].T, nan=0.0))[:, 1]
        cand[(i, j)] = (idx, pot)
        if potential_prefix:
            pm = np.full(start.size, -9999, "float32")
            pm[idx] = pot
            store.outputs[f"{potential_prefix}_{i}to{j}.tif"] = to_geotiff_bytes(r0.profile, pm.reshape(start.shape), "float32", -9999)
    sim, unmet = allocate(start, valid, cand, demand, int(neighbourhood), float(weight), int(iterations), protected, float(stochastic), seed)
    nod = 0 if start[valid].min(initial=1) > 0 else 65535
    dtype = "uint8" if nod == 0 and sim[valid].max(initial=0) < 255 else "uint16"
    store.outputs[output_name] = to_geotiff_bytes(r0.profile, np.where(valid, sim, nod), dtype, nod)
    pa = res * res / 1e4
    cls_l = [int(c) for c in cls]
    area = pd.DataFrame({"class": cls_l, "start_ha": [((start == c) & valid).sum() * pa for c in cls_l],
                         "simulated_ha": [((sim == c) & valid).sum() * pa for c in cls_l]})
    area["change_ha"] = area["simulated_ha"] - area["start_ha"]
    total_change = sum(M[i, j] for i in range(len(cls)) for j in range(len(cls)) if i != j)
    covered = sum(c for _, _, c in tr)
    return dict(output=output_name, start_year=start_year, protected_pixels=int(protected.sum()) if protected is not None else 0, calibration=f"{map_from} ({year_from}) -> {map_to} ({year_to})", start_map=start_map, target_year=year_target,
                scenario=scenario, model=model, drivers=[driver_name(d) for d in drivers],
                transitions_modelled=auc.round(4).to_dict(orient="records"),
                share_of_calibration_change_modelled=float(covered / total_change) if total_change else None,
                markov_matrix=dict(classes=cls_l, P=np.round(Q, 5).tolist(), years=years_target),
                demand_pixels={f"{i}->{j}": int(round(v)) for (i, j), v in demand.items()},
                unmet_demand_pixels={k: v for k, v in unmet.items() if v > 0},
                area_table=area.round(2).to_dict(orient="records"),
                potential_maps=[k for k in store.outputs if potential_prefix and k.startswith(potential_prefix + "_")],
                note="A simulated map is a scenario, not a forecast. Validate the same settings in a hindcast (simulate a known date) "
                     "and report figure of merit and Kappa simulation before presenting future scenarios.")


def validate(store, initial, observed, simulated_maps):
    names = [initial, observed] + list(simulated_maps)
    rs = _grid(store, names)
    valid = np.logical_and.reduce([~r.mask for r in rs])
    i, o = _cat(rs[0])[valid], _cat(rs[1])[valid]
    rows = [dict(model="Null (persistence)", **compare(i, o, i.copy()))]
    for n, r in zip(simulated_maps, rs[2:]):
        rows.append(dict(model=n, **compare(i, o, _cat(r)[valid])))
    df = pd.DataFrame(rows)
    best = df.iloc[1:].sort_values("fom", ascending=False)["model"].iloc[0] if len(df) > 1 else None
    return dict(initial=initial, observed=observed, compared_pixels=int(valid.sum()),
                results=[{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in df.to_dict(orient="records")],
                best_by_fom=best,
                note="Null model = no change; a useful simulation must beat it on Kappa simulation and have FoM > 0. Typical published FoM "
                     "values are 0.1-0.3 (Pontius et al. 2008). High overall agreement alone mostly reflects persistence.")


def make_driver_layers(store, base_map, classes=(), layers=(), dem=None, prefix="drv"):
    """Write distance / slope driver GeoTIFFs (also usable in MOLUSCE)."""
    names_needed = [base_map] + list(layers) + ([dem] if dem else [])
    _grid(store, names_needed)
    r = store.get(base_map)
    res = _res(r)
    a = _cat(r)
    out = []
    for c in classes:
        arr = distance_to((a == int(c)) & ~r.mask, res)
        n = f"{prefix}_dist_class{int(c)}.tif"
        store.outputs[n] = to_geotiff_bytes(r.profile, np.where(r.mask, -9999, arr), "float32", -9999)
        out.append(n)
    for lay in layers:
        lr = store.get(lay)
        n = f"{prefix}_dist_{lay.rsplit('.', 1)[0]}.tif"
        store.outputs[n] = to_geotiff_bytes(r.profile, np.where(r.mask, -9999, distance_to((lr.data != 0) & ~lr.mask, res)), "float32", -9999)
        out.append(n)
    if dem:
        dr = store.get(dem)
        n = f"{prefix}_slope_{dem.rsplit('.', 1)[0]}.tif"
        store.outputs[n] = to_geotiff_bytes(r.profile, np.where(dr.mask, -9999, slope_deg(np.where(dr.mask, np.nanmean(dr.data[~dr.mask]), dr.data), res)), "float32", -9999)
        out.append(n)
    return dict(outputs=out, note="Distances in metres; slope in degrees (Horn 1981). The files can also be used as MOLUSCE factors.")
