"""Linking LULC maps and scenarios to SWAT+ and to first-order hydrological and erosion responses (v1.0.0).

* LULC class -> SWAT+ land-use code lookup (QSWAT+ CSV: LANDUSE_ID,SWAT_CODE) with area per code
* SCS Curve Number runoff (USDA-NRCS 1986, TR-55) per LULC scenario: CN by SWAT code and hydrologic soil group, SWAT slope
  adjustment of CN2 (Williams 1995; Neitsch et al. 2011, eq. 2:1.1.4), design storm or daily rainfall series, Ia = 0.2 S or 0.05 S
  (Hawkins et al. 2002)
* RUSLE soil loss A = R K LS C P (Renard et al. 1997): C by SWAT code, LS from a DEM with a fixed slope length (Wischmeier & Smith
  1978) or D8 flow accumulation (Moore & Burch 1986)
* Streamflow evaluation: flow-duration curves, Yilmaz et al. (2008) FDC signatures, RSR, Moriasi et al. (2007, 2015) ratings,
  calibration / validation split, daily / monthly / annual aggregation, and attribution of a LULC change between two SWAT+ runs

The CN and C tables are editable defaults from the literature: check them against your SWAT+ plants / urban databases and local studies.
"""
import math
import re

import numpy as np
import pandas as pd

import hydro
import metrics
from rasterops import _projected_metres
from simulate import slope_deg
from store import to_geotiff_bytes

# ------------------------------------------------------------------ tables
# code: (description, CN2 for HSG A, B, C, D [TR-55, AMC II], RUSLE C)
SWAT_TABLE = {
    "WATR": ("Water", 98, 98, 98, 98, 0.0),
    "WETF": ("Wetlands-forested", 45, 66, 77, 83, 0.003),
    "WETN": ("Wetlands-non-forested", 49, 69, 79, 84, 0.01),
    "FRST": ("Forest-mixed", 36, 60, 73, 79, 0.003),
    "FRSD": ("Forest-deciduous", 36, 60, 73, 79, 0.004),
    "FRSE": ("Forest-evergreen", 30, 55, 70, 77, 0.002),
    "RNGB": ("Range-brush (shrubland)", 35, 56, 70, 77, 0.03),
    "RNGE": ("Range-grasses", 49, 69, 79, 84, 0.05),
    "PAST": ("Pasture", 49, 69, 79, 84, 0.05),
    "AGRL": ("Agricultural land-generic", 67, 77, 83, 87, 0.25),
    "AGRR": ("Agricultural land-row crops", 67, 78, 85, 89, 0.35),
    "AGRC": ("Agricultural land-close-grown", 63, 75, 83, 87, 0.15),
    "RICE": ("Rice", 72, 81, 88, 91, 0.15),
    "ORCD": ("Orchard", 43, 65, 76, 82, 0.15),
    "URLD": ("Residential-low density", 51, 68, 79, 84, 0.01),
    "URMD": ("Residential-medium density", 61, 75, 83, 87, 0.005),
    "URHD": ("Residential-high density", 77, 85, 90, 92, 0.003),
    "UCOM": ("Commercial", 89, 92, 94, 95, 0.0),
    "UIDU": ("Industrial", 81, 88, 91, 93, 0.0),
    "UTRN": ("Transportation", 98, 98, 98, 98, 0.0),
    "BARR": ("Barren", 77, 86, 91, 94, 0.6),
}

KEYWORDS = [
    (r"water|river|lake|reservoir|sea|pond|canal", "WATR"), (r"wet ?land|marsh|swamp|mangrove|bog", "WETN"),
    (r"evergreen|conifer|pine|spruce", "FRSE"), (r"deciduous|broadleaf", "FRSD"), (r"forest|wood|tree", "FRST"),
    (r"shrub|scrub|bush", "RNGB"), (r"pasture", "PAST"), (r"grass|range|meadow|steppe|savanna", "RNGE"),
    (r"rice|paddy", "RICE"), (r"orchard|plantation|vineyard", "ORCD"), (r"wheat|grain|cereal", "AGRC"),
    (r"crop|agri|farm|cultivat|cropland", "AGRL"), (r"industr", "UIDU"), (r"commercial", "UCOM"), (r"road|transport|airport", "UTRN"),
    (r"built|urban|settle|residential|city|town|impervious", "URMD"), (r"bare|barren|sand|rock|soil|desert|mine|snow|ice|glacier", "BARR"),
]

HSG = {1: "A", 2: "B", 3: "C", 4: "D"}


def suggest_code(name):
    n = name.lower() if isinstance(name, str) else ""
    for pat, code in KEYWORDS:
        if re.search(pat, n):
            return code
    return None


def _codes_for(classes, labels=None, swat_codes=None):
    out, missing = {}, []
    for c in classes:
        code = (swat_codes or {}).get(str(c)) or suggest_code((labels or {}).get(str(c), ""))
        if code and code.upper() in SWAT_TABLE:
            out[int(c)] = code.upper()
        else:
            missing.append(int(c))
    return out, missing


def _cat(r):
    return r.data.astype(np.int64)


def _grid(store, names):
    rs = [store.get(n) for n in names]
    g = rs[0]
    _projected_metres(g)
    for r, n in zip(rs[1:], names[1:]):
        if r.data.shape != g.data.shape or not np.allclose(tuple(r.transform)[:6], tuple(g.transform)[:6]):
            raise ValueError(f"{n} is not on the same grid as {names[0]}; align the rasters first.")
    return rs


def _cell(r):
    return abs(r.transform.a)


# ------------------------------------------------------------------ lookup
def swat_lookup(store, layers, labels=None, swat_codes=None):
    if isinstance(layers, str):
        layers = [layers]
    rs = _grid(store, layers)
    classes = sorted({int(v) for r in rs for v in np.unique(r.data[~r.mask])})
    codes, missing = _codes_for(classes, labels, swat_codes)
    pa = _cell(rs[0]) ** 2 / 1e4
    area = []
    for n, r in zip(layers, rs):
        v, c = np.unique(_cat(r)[~r.mask], return_counts=True)
        for k, cnt in zip(v, c):
            area.append(dict(layer=n, class_code=int(k), class_name=(labels or {}).get(str(int(k)), ""), swat_code=codes.get(int(k), "?"),
                             area_ha=round(float(cnt) * pa, 2)))
    csv = "LANDUSE_ID,SWAT_CODE\n" + "".join(f"{c},{codes[c]}\n" for c in classes if c in codes)
    return dict(lookup={str(c): codes.get(c) for c in classes}, unmapped_classes=missing, lookup_csv=csv,
                area_by_class=area, swat_codes={k: v[0] for k, v in SWAT_TABLE.items()},
                note="Load lookup_csv in QSWAT+ as the landuse lookup table. Codes were suggested from class names; confirm them, and give "
                     "swat_codes for any unmapped class.")


# ------------------------------------------------------------------ curve number
def cn_slope_adjust(cn2, slope_frac):
    """SWAT (Williams 1995) slope adjustment of CN2 (defined for 5 % slope)."""
    cn3 = cn2 * np.exp(0.00673 * (100 - cn2))
    return np.clip((cn3 - cn2) / 3 * (1 - 2 * np.exp(-13.86 * slope_frac)) + cn2, 1, 100)


def runoff_mm(P, cn, lam=0.2):
    """SCS-CN direct runoff depth (mm). lam = 0.2 (TR-55) or 0.05 (with S converted, Hawkins et al. 2002)."""
    cn = np.asarray(cn, float)
    S = 25400.0 / np.clip(cn, 1, 100) - 254.0
    if lam == 0.05:
        S = 1.42 * S
    Ia = lam * S
    P = np.asarray(P, float)
    return np.where(P > Ia, (P - Ia) ** 2 / (P - Ia + S), 0.0)


def _cn_grid(store, layer, codes, hsg, hsg_uniform, dem, cn_overrides):
    r = store.get(layer)
    a = _cat(r)
    cn = np.full(a.shape, np.nan, "float32")
    if hsg is not None:
        h = hsg.data.astype(np.int64)
        hvalid = np.isin(h, [1, 2, 3, 4]) & ~hsg.mask
    for c, code in codes.items():
        vals = cn_overrides.get(code) if cn_overrides and code in cn_overrides else SWAT_TABLE[code][1:5]
        m = (a == c) & ~r.mask
        if hsg is None:
            cn[m] = vals["ABCD".index(hsg_uniform)]
        else:
            for g in range(1, 5):
                cn[m & hvalid & (h == g)] = vals[g - 1]
    if dem is not None:
        slp = np.tan(np.radians(slope_deg(np.where(dem.mask, np.nanmean(dem.data[~dem.mask]), dem.data), _cell(r))))
        ok = np.isfinite(cn)
        cn[ok] = cn_slope_adjust(cn[ok], slp[ok])
    return cn


def curve_number_runoff(store, layers, labels=None, swat_codes=None, hsg_layer=None, hsg_uniform="B", dem=None, storm_mm=50.0,
                        rain_table=None, date_col=None, rain_col=None, lam=0.2, cn_overrides=None, write_maps=True):
    if isinstance(layers, str):
        layers = [layers]
    names = list(layers) + ([hsg_layer] if hsg_layer else []) + ([dem] if dem else [])
    rs = _grid(store, names)
    classes = sorted({int(v) for r in rs[:len(layers)] for v in np.unique(r.data[~r.mask])})
    codes, missing = _codes_for(classes, labels, swat_codes)
    if missing:
        raise ValueError(f"Classes {missing} have no SWAT+ code; give swat_codes or class names (labels).")
    hsg = store.get(hsg_layer) if hsg_layer else None
    demr = store.get(dem) if dem else None
    if hsg_uniform not in "ABCD":
        raise ValueError("hsg_uniform must be A, B, C or D")
    cell_area = _cell(rs[0]) ** 2
    series = None
    if rain_table is not None:
        series = pd.DataFrame({"date": pd.to_datetime(rain_table[date_col], errors="coerce"),
                               "P": pd.to_numeric(rain_table[rain_col], errors="coerce")}).dropna()
        if series.empty:
            raise ValueError("Rainfall table has no valid date / rainfall rows.")
    rows, outputs = [], []
    for n in layers:
        cn = _cn_grid(store, n, codes, hsg, hsg_uniform, demr, cn_overrides)
        ok = np.isfinite(cn)
        q = runoff_mm(storm_mm, cn[ok], lam)
        row = dict(layer=n, mean_CN=float(cn[ok].mean()), storm_mm=float(storm_mm), storm_runoff_mm=float(q.mean()),
                   storm_runoff_coefficient=float(q.mean() / storm_mm) if storm_mm else None,
                   storm_runoff_volume_m3=float(q.sum() / 1000 * cell_area), area_ha=float(ok.sum() * cell_area / 1e4))
        if series is not None:
            u, cnt = np.unique(np.round(cn[ok], 1), return_counts=True)
            w = cnt / cnt.sum()
            Q = runoff_mm(series["P"].to_numpy()[:, None], u[None, :], lam) @ w     # daily runoff depth (area-weighted)
            yrs = (series["date"].max() - series["date"].min()).days / 365.25
            row.update(series_days=int(len(series)), mean_annual_rain_mm=float(series["P"].sum() / max(yrs, 1e-9)),
                       mean_annual_runoff_mm=float(Q.sum() / max(yrs, 1e-9)), series_runoff_coefficient=float(Q.sum() / series["P"].sum()))
        rows.append(row)
        if write_maps:
            base = n.rsplit(".", 1)[0]
            g = store.get(n)
            store.outputs[f"{base}_CN.tif"] = to_geotiff_bytes(g.profile, np.where(ok, cn, -9999), "float32", -9999)
            qm = np.full(cn.shape, -9999, "float32")
            qm[ok] = q
            store.outputs[f"{base}_runoff_{int(storm_mm)}mm.tif"] = to_geotiff_bytes(g.profile, qm, "float32", -9999)
            outputs += [f"{base}_CN.tif", f"{base}_runoff_{int(storm_mm)}mm.tif"]
    df = pd.DataFrame(rows)
    base = df.iloc[0]
    for col in [c for c in ("mean_CN", "storm_runoff_mm", "storm_runoff_volume_m3", "mean_annual_runoff_mm") if c in df]:
        df[f"change_{col}_pct_vs_first"] = (df[col] - base[col]) / base[col] * 100 if base[col] else np.nan
    return dict(lookup={str(k): v for k, v in codes.items()}, hsg=("raster " + hsg_layer) if hsg_layer else f"uniform {hsg_uniform}",
                slope_adjusted=bool(dem), initial_abstraction_ratio=lam, results=df.round(4).to_dict(orient="records"), outputs=outputs,
                note="SCS-CN is an event model: use it to compare LULC scenarios under the same rainfall, not as a substitute for a calibrated "
                     "SWAT+ run. Run SWAT+ with each scenario map (same climate, frozen parameters) for the full water balance.")


# ------------------------------------------------------------------ RUSLE
def d8_accumulation(dem, cell):
    """Upslope contributing cells (incl. itself) by D8 steepest descent; pits and edges stop flow."""
    H, W = dem.shape
    z = np.pad(dem.astype("float64"), 1, constant_values=np.inf)
    best = np.zeros((H, W))
    rec = np.full((H, W), -1, np.int64)
    idx = np.arange(H * W).reshape(H, W)
    for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        nb = z[1 + dr:H + 1 + dr, 1 + dc:W + 1 + dc]
        drop = (dem - nb) / (cell * math.hypot(dr, dc))
        better = np.isfinite(nb) & (drop > best)
        best = np.where(better, drop, best)
        rr = np.clip(np.arange(H)[:, None] + dr, 0, H - 1)
        cc = np.clip(np.arange(W)[None, :] + dc, 0, W - 1)
        rec = np.where(better, idx[rr, cc], rec)
    rec = rec.ravel()
    acc = np.ones(H * W)
    has = rec >= 0
    indeg = np.bincount(rec[has], minlength=H * W)
    front = np.flatnonzero(indeg == 0)
    while front.size:
        f = front[rec[front] >= 0]
        r = rec[f]
        np.add.at(acc, r, acc[f])
        np.subtract.at(indeg, r, 1)
        u = np.unique(r)
        front = u[indeg[u] == 0]
    return acc.reshape(H, W)


def ls_factor(dem, cell, method="slope_length", slope_length=50.0, max_length=300.0):
    theta = np.radians(slope_deg(dem, cell))
    s = np.sin(theta)
    if method == "slope_length":
        pct = np.tan(theta) * 100
        m = np.select([pct >= 5, pct >= 3.5, pct >= 1], [0.5, 0.4, 0.3], 0.2)
        return (slope_length / 22.13) ** m * (65.41 * s * s + 4.56 * s + 0.065)
    acc = d8_accumulation(dem, cell)
    As = np.minimum(acc * cell, max_length)   # specific catchment area (m2/m), capped
    return (As / 22.13) ** 0.4 * (s / 0.0896) ** 1.3


def _num_or_layer(store, v, shape):
    if isinstance(v, (int, float)):
        return np.full(shape, float(v), "float32"), None
    r = store.get(v)
    a = r.data.astype("float32")
    a[r.mask] = np.nan
    return a, v


SEVERITY = [(0, 5, "low"), (5, 10, "moderate"), (10, 20, "high"), (20, 40, "very high"), (40, np.inf, "severe")]


def rusle(store, layers, dem, R=500.0, K=0.03, P=1.0, labels=None, swat_codes=None, ls_method="slope_length", slope_length=50.0,
          max_length=300.0, c_overrides=None, write_maps=True):
    if isinstance(layers, str):
        layers = [layers]
    names = list(layers) + [dem] + [x for x in (R, K, P) if isinstance(x, str)]
    rs = _grid(store, names)
    classes = sorted({int(v) for r in rs[:len(layers)] for v in np.unique(r.data[~r.mask])})
    codes, missing = _codes_for(classes, labels, swat_codes)
    if missing:
        raise ValueError(f"Classes {missing} have no SWAT+ code / C factor; give swat_codes or class names (labels).")
    d = store.get(dem)
    cell = _cell(d)
    shape = d.data.shape
    LS = ls_factor(np.where(d.mask, np.nanmean(d.data[~d.mask]), d.data).astype("float64"), cell, ls_method, slope_length, max_length)
    Ra, _ = _num_or_layer(store, R, shape)
    Ka, _ = _num_or_layer(store, K, shape)
    Pa, _ = _num_or_layer(store, P, shape)
    base_rkls = Ra * Ka * LS * Pa
    pa = cell * cell / 1e4
    rows, by_class, outputs = [], [], []
    for n in layers:
        r = store.get(n)
        a = _cat(r)
        C = np.full(shape, np.nan, "float32")
        for c, code in codes.items():
            C[(a == c) & ~r.mask] = (c_overrides or {}).get(code, SWAT_TABLE[code][5])
        A = base_rkls * C
        ok = np.isfinite(A) & ~d.mask
        Av = A[ok]
        row = dict(layer=n, mean_soil_loss_t_ha_yr=float(Av.mean()), total_soil_loss_t_yr=float(Av.sum() * pa),
                   area_ha=float(ok.sum() * pa))
        for lo, hi, lab in SEVERITY:
            row[f"{lab}_pct_area"] = float(((Av >= lo) & (Av < hi)).mean() * 100)
        rows.append(row)
        for c, code in codes.items():
            m = ok & (a == c)
            if m.any():
                by_class.append(dict(layer=n, class_code=c, swat_code=code, C=float((c_overrides or {}).get(code, SWAT_TABLE[code][5])),
                                     area_ha=float(m.sum() * pa), mean_t_ha_yr=float(A[m].mean()), total_t_yr=float(A[m].sum() * pa)))
        if write_maps:
            out = f"{n.rsplit('.', 1)[0]}_soil_loss.tif"
            store.outputs[out] = to_geotiff_bytes(r.profile, np.where(ok, A, -9999).astype("float32"), "float32", -9999)
            outputs.append(out)
    if write_maps:
        store.outputs["LS_factor.tif"] = to_geotiff_bytes(d.profile, np.where(d.mask, -9999, LS).astype("float32"), "float32", -9999)
        outputs.append("LS_factor.tif")
    df = pd.DataFrame(rows)
    if len(df) > 1 and df["total_soil_loss_t_yr"].iloc[0]:
        df["change_total_pct_vs_first"] = (df["total_soil_loss_t_yr"] / df["total_soil_loss_t_yr"].iloc[0] - 1) * 100
    return dict(R=R, K=K, P=P, ls_method=ls_method, slope_length_m=slope_length, mean_LS=float(np.nanmean(LS[~d.mask])),
                results=df.round(4).to_dict(orient="records"), by_class=pd.DataFrame(by_class).round(4).to_dict(orient="records"),
                outputs=outputs, severity_classes_t_ha_yr="low <5, moderate 5-10, high 10-20, very high 20-40, severe >40",
                note="RUSLE gives long-term average sheet and rill erosion; it ignores gullies and deposition. Units: R in MJ mm ha-1 h-1 yr-1, "
                     "K in t ha h ha-1 MJ-1 mm-1, A in t ha-1 yr-1. Compare scenarios with the same R, K, LS and P.")


# ------------------------------------------------------------------ streamflow evaluation
MORIASI = {
    # metric: [(test, rating)] for watershed-scale streamflow, Moriasi et al. 2015 (NSE, R2, PBIAS) and 2007 (RSR)
    "nse": [(lambda v: v > 0.80, "very good"), (lambda v: v > 0.70, "good"), (lambda v: v > 0.50, "satisfactory")],
    "r2": [(lambda v: v > 0.85, "very good"), (lambda v: v > 0.75, "good"), (lambda v: v > 0.60, "satisfactory")],
    "pbias_percent": [(lambda v: abs(v) < 5, "very good"), (lambda v: abs(v) < 10, "good"), (lambda v: abs(v) < 15, "satisfactory")],
    "rsr": [(lambda v: v <= 0.50, "very good"), (lambda v: v <= 0.60, "good"), (lambda v: v <= 0.70, "satisfactory")],
}


def rate(metric, v):
    if v is None or not np.isfinite(v):
        return "n/a"
    for test, lab in MORIASI[metric]:
        if test(v):
            return lab
    return "unsatisfactory"


def fdc(q):
    q = np.sort(np.asarray(q, float))[::-1]
    p = np.arange(1, q.size + 1) / (q.size + 1)
    return p, q


def fdc_signatures(obs, sim):
    """Yilmaz et al. (2008): %BiasFHV (top 2 %), %BiasFLV (bottom 30 %, log), %BiasFMS (0.2-0.7 exceedance slope, log)."""
    eps = 1e-6
    po, qo = fdc(obs)
    ps, qs = fdc(sim)
    h = max(1, int(round(0.02 * qo.size)))
    fhv = (qs[:h] - qo[:h]).sum() / qo[:h].sum() * 100 if qo[:h].sum() else np.nan
    lo = po >= 0.7
    lqo, lqs = np.log(np.maximum(qo[lo], eps)), np.log(np.maximum(qs[ps >= 0.7], eps))
    so, ss = (lqo - lqo.min()).sum(), (lqs - lqs.min()).sum()
    flv = -1 * (ss - so) / so * 100 if so else np.nan

    def q_at(p, q, x):
        return np.log(max(np.interp(x, p, q), eps))
    do = q_at(po, qo, 0.2) - q_at(po, qo, 0.7)
    ds = q_at(ps, qs, 0.2) - q_at(ps, qs, 0.7)
    fms = (ds - do) / do * 100 if do else np.nan
    return dict(pbias_fhv=float(fhv), pbias_flv=float(flv), pbias_fms=float(fms))


def _aggregate(m, step):
    if step == "daily":
        return m
    rule = {"monthly": "MS", "annual": "YS"}[step]
    g = m.set_index("date")[["obs", "sim"]].resample(rule).mean().dropna().reset_index()
    return g


def _scores(m):
    o, s = m["obs"].to_numpy(), m["sim"].to_numpy()
    rmse = float(np.sqrt(((o - s) ** 2).mean()))
    rsr = rmse / o.std() if o.std() else np.nan
    sc = dict(n=int(len(m)), nse=metrics.nse(o, s), kge=metrics.kge(o, s), r2=metrics.r2(o, s), pbias_percent=metrics.pbias(o, s), rsr=float(rsr),
              **fdc_signatures(o, s))
    sc["ratings"] = {k: rate(k, sc[k]) for k in ("nse", "r2", "pbias_percent", "rsr")}
    sc["kge_beats_mean_benchmark"] = bool(sc["kge"] > 1 - math.sqrt(2)) if np.isfinite(sc["kge"]) else None
    return sc


def flow_evaluation(obs_df, sim_df, date_col, obs_col, sim_col, split_date=None, step="daily", warmup_end=None):
    m = hydro.align(obs_df, sim_df, date_col, obs_col, sim_col, start=warmup_end)
    if len(m) < 10:
        raise ValueError("Fewer than 10 matching dates.")
    m = _aggregate(m, step)
    out = dict(step=step, period=f"{m['date'].min().date()} to {m['date'].max().date()}", all=_scores(m))
    if split_date:
        sd = pd.to_datetime(split_date)
        cal, val = m[m["date"] < sd], m[m["date"] >= sd]
        if len(cal) >= 5:
            out["calibration"] = _scores(cal)
        if len(val) >= 5:
            out["validation"] = _scores(val)
    p_o, q_o = fdc(m["obs"])
    p_s, q_s = fdc(m["sim"])
    grid = np.linspace(0.001, 0.999, 120)
    out["fdc"] = dict(exceedance=grid.round(4).tolist(), obs=np.interp(grid, p_o, q_o).round(5).tolist(), sim=np.interp(grid, p_s, q_s).round(5).tolist())
    out["note"] = ("Ratings follow Moriasi et al. (2015) for streamflow (NSE, R2, PBIAS; PBIAS > 0 = underestimation) and Moriasi et al. (2007) "
                   "for RSR. KGE > -0.41 beats the mean-flow benchmark (Knoben et al. 2019). FDC signatures: FHV = high-flow volume bias, "
                   "FLV = low-flow bias, FMS = mid-segment slope bias (Yilmaz et al. 2008).")
    return out


def lulc_attribution(base_df, scen_df, date_col, base_col, scen_col):
    """Compare two SWAT+ runs that differ only in the LULC map (same climate, frozen parameters)."""
    m = hydro.align(base_df, scen_df, date_col, base_col, scen_col)
    if len(m) < 10:
        raise ValueError("Fewer than 10 matching dates.")
    b, s = m["obs"].to_numpy(), m["sim"].to_numpy()

    def pct(x, y):
        return float((y - x) / x * 100) if x else np.nan
    q = {f"Q{k}": (float(np.percentile(b, 100 - k)), float(np.percentile(s, 100 - k))) for k in (5, 50, 95)}
    ann = m.set_index("date")[["obs", "sim"]].resample("YS").mean()
    pb, qb = fdc(b)
    ps, qs = fdc(s)
    grid = np.linspace(0.001, 0.999, 120)
    return dict(n=int(len(m)), mean_baseline=float(b.mean()), mean_scenario=float(s.mean()), mean_change_pct=pct(b.mean(), s.mean()),
                **{f"{k}_change_pct": pct(*v) for k, v in q.items()}, flow_quantiles={k: dict(baseline=v[0], scenario=v[1]) for k, v in q.items()},
                annual=[dict(year=int(i.year), baseline=float(r.obs), scenario=float(r.sim)) for i, r in ann.iterrows()],
                fdc=dict(exceedance=grid.round(4).tolist(), baseline=np.interp(grid, pb, qb).round(5).tolist(), scenario=np.interp(grid, ps, qs).round(5).tolist()),
                note="Q5 = high flow exceeded 5 % of the time, Q95 = low flow. With climate and parameters held constant the differences are "
                     "attributable to the LULC change (one-factor-at-a-time design).")
