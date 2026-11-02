"""Thesis-style report generator (v1.2.0).

Collects every analysis run in the session (full tool results are kept by agent_tools.run_tool), writes a methods-and-results
narrative with the numbers that were actually computed, numbered tables and figures (finished maps from cartography.compose_map
and charts), a reference list limited to the methods used, and the processing log as an appendix.
Outputs: Word (.docx, editable) and a self-contained print-ready HTML file (open it and print to PDF).
"""
import base64
import datetime
import html
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from rasterio.io import MemoryFile  # noqa: E402

import cartography  # noqa: E402

SKIP = {"list_session", "describe_table", "inspect_raster", "describe_vector", "practical_guide", "generate_report", "record_model_settings"}

REFS = {
    "hall": "Hall, D. K., Riggs, G. A., & Salomonson, V. V. (1995). Development of methods for mapping global snow cover using moderate resolution imaging spectroradiometer data. Remote Sensing of Environment, 54(2), 127-140.",
    "olofsson": "Olofsson, P., Foody, G. M., Herold, M., Stehman, S. V., Woodcock, C. E., & Wulder, M. A. (2014). Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment, 148, 42-57.",
    "pontius2011": "Pontius, R. G., Jr., & Millones, M. (2011). Death to Kappa: birth of quantity disagreement and allocation disagreement for accuracy assessment. International Journal of Remote Sensing, 32(15), 4407-4429.",
    "pontius2014": "Pontius, R. G., Jr., & Santacruz, A. (2014). Quantity, exchange, and shift components of difference in a square contingency table. International Journal of Remote Sensing, 35(21), 7543-7554.",
    "aldwaik": "Aldwaik, S. Z., & Pontius, R. G., Jr. (2012). Intensity analysis to unify measurements of size and stationarity of land changes by interval, category, and transition. Landscape and Urban Planning, 106(1), 103-114.",
    "pontius2017": "Pontius, R. G., Jr., Krithivasan, R., Sauls, L., Yan, Y., & Zhang, Y. (2017). Methods to summarize change among land categories across time intervals. Journal of Land Use Science, 12(4), 218-230.",
    "fragstats": "McGarigal, K., Cushman, S. A., & Ene, E. (2023). FRAGSTATS v4: Spatial Pattern Analysis Program for Categorical Maps. University of Massachusetts, Amherst.",
    "getis": "Ord, J. K., & Getis, A. (1995). Local spatial autocorrelation statistics: distributional issues and an application. Geographical Analysis, 27(4), 286-306.",
    "anselin": "Anselin, L. (1995). Local indicators of spatial association—LISA. Geographical Analysis, 27(2), 93-115.",
    "bh": "Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: a practical and powerful approach to multiple testing. Journal of the Royal Statistical Society B, 57(1), 289-300.",
    "breiman": "Breiman, L. (2001). Random forests. Machine Learning, 45(1), 5-32.",
    "roberts": "Roberts, D. R., et al. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. Ecography, 40(8), 913-929.",
    "ploton": "Ploton, P., et al. (2020). Spatial validation reveals poor predictive performance of large-scale ecological mapping models. Nature Communications, 11, 4540.",
    "fom": "Pontius, R. G., Jr., et al. (2008). Comparing the input, output, and validation maps for several models of land change. The Annals of Regional Science, 42(1), 11-37.",
    "vanvliet": "van Vliet, J., Bregt, A. K., & Hagen-Zanker, A. (2011). Revisiting Kappa to account for change in the accuracy assessment of land-use change models. Ecological Modelling, 222(8), 1367-1375.",
    "tr55": "USDA-NRCS (1986). Urban Hydrology for Small Watersheds, Technical Release 55 (TR-55). United States Department of Agriculture.",
    "swat": "Neitsch, S. L., Arnold, J. G., Kiniry, J. R., & Williams, J. R. (2011). Soil and Water Assessment Tool Theoretical Documentation, Version 2009. Texas Water Resources Institute.",
    "rusle": "Renard, K. G., Foster, G. R., Weesies, G. A., McCool, D. K., & Yoder, D. C. (1997). Predicting Soil Erosion by Water: A Guide to Conservation Planning with RUSLE. USDA Agriculture Handbook 703.",
    "moriasi2015": "Moriasi, D. N., Gitau, M. W., Pai, N., & Daggupati, P. (2015). Hydrologic and water quality models: performance measures and evaluation criteria. Transactions of the ASABE, 58(6), 1763-1785.",
    "moriasi2007": "Moriasi, D. N., et al. (2007). Model evaluation guidelines for systematic quantification of accuracy in watershed simulations. Transactions of the ASABE, 50(3), 885-900.",
    "yilmaz": "Yilmaz, K. K., Gupta, H. V., & Wagener, T. (2008). A process-based diagnostic approach to model evaluation: application to the NWS distributed hydrologic model. Water Resources Research, 44(9).",
    "gupta": "Gupta, H. V., Kling, H., Yilmaz, K. K., & Martinez, G. F. (2009). Decomposition of the mean squared error and NSE performance criteria. Journal of Hydrology, 377(1-2), 80-91.",
    "markov": "Eastman, J. R. (2016). TerrSet Geospatial Monitoring and Modeling System Manual (Land Change Modeler). Clark University.",
    "cramer": "Cramér, H. (1946). Mathematical Methods of Statistics. Princeton University Press.",
}


# ------------------------------------------------------------------ helpers
def _fmt(v, nd=3):
    if isinstance(v, float):
        return "n/a" if not np.isfinite(v) else (f"{v:,.{nd}f}" if abs(v) < 1e5 else f"{v:,.0f}")
    return str(v)


def _df(records, cols=None, max_rows=40):
    df = pd.DataFrame(records)
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    return df.head(max_rows)


def _png(fig, dpi=170):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


_LABELS = {}


def _map(ctx, name, title, labels=None, version=""):
    labels = labels or (_LABELS or None)
    raw = ctx.store.outputs.get(name)
    if raw is None:
        try:
            r = ctx.store.get(name)
            arr, mask, tr, crs = r.data, r.mask, r.transform, r.crs
        except Exception:
            return None
    else:
        with MemoryFile(raw) as mf, mf.open() as src:
            arr = src.read(1)
            nd = src.nodata
            tr, crs = src.transform, src.crs
        mask = (arr == nd) if nd is not None else np.zeros(arr.shape, bool)
        if arr.dtype.kind == "f":
            mask |= ~np.isfinite(arr)
    try:
        fig = cartography.compose_map(arr, mask, tr, crs, title=title, labels={str(k): v for k, v in (labels or {}).items()} if labels else None,
                                      layer_name=name, version=version)
        return cartography.fig_bytes(fig, dpi=150)
    except Exception:
        return None


def _barh(labels, values, xlabel, colour="#7C3AED", title=None, ref=None, ref_label=None):
    fig, ax = plt.subplots(figsize=(6.4, 0.32 * len(labels) + 1.2))
    ax.barh(range(len(labels)), values, color=colour)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    if ref is not None:
        ax.axvline(ref, color="#111", ls="--", lw=1.2, label=ref_label)
        ax.legend(fontsize=8, frameon=False)
    if title:
        ax.set_title(title, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    return _png(fig)


def _lines(x, series, xlabel, ylabel, logy=False, title=None):
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for (lab, y), c in zip(series.items(), ["#06B6D4", "#EC4899", "#F97316", "#10B981"]):
        ax.plot(x, y, label=lab, color=c, lw=1.6)
    if logy:
        ax.set_yscale("symlog")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, fontsize=8)
    if title:
        ax.set_title(title, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    return _png(fig)


# ------------------------------------------------------------------ section builders: (blocks, refs)
def _b_hyps(ctx, a, r):
    b = _df(r["bands"], ["from_m", "to_m", "area_km2", "area_pct", "cumulative_km2", "cumulative_pct"], 40)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    mids = (b["from_m"] + b["to_m"]) / 2
    ax.barh(mids, b["area_km2"], height=(b["to_m"] - b["from_m"]) * 0.8, color="#15803D", label="area per band")
    ax.set_xlabel("Area per band (km²)")
    ax.set_ylabel("Elevation (m)")
    ax2 = ax.twiny()
    ax2.plot(b["cumulative_km2"], b["to_m"], color="#DC2626", marker="D", ms=4, label="hypsometric curve")
    ax2.set_xlabel("Cumulative area (km²)")
    fig.legend(loc="lower right", fontsize=8, frameon=False)
    return [("p", f"The basin covers {r['area_km2']:,.0f} km² between {r['min_m']:,.0f} and {r['max_m']:,.0f} m (mean {r['mean_m']:,.0f} m, median "
                  f"{r['median_m']:,.0f} m; 90% of the area lies between {r['percentiles_m']['p5']:,.0f} and {r['percentiles_m']['p95']:,.0f} m). The hypsometric "
                  f"integral is {r['hypsometric_integral']:.2f}. " + r["note"]),
            ("table", b, "Area per elevation band"), ("fig", _png(fig), "Area per elevation band and hypsometric curve")], []


def _b_snow(ctx, a, r):
    blocks = [("p", f"Snow and ice were mapped where NDSI > {r['ndsi_threshold']} and NIR reflectance > {r['nir_threshold']} (Hall et al. 1995)"
                    + (", with water masked by WorldCover" if r["water_masked"] else "") + f": {r['snow_ice_km2']:,.1f} km² ({r['snow_ice_pct']:.1f}% of the "
                    f"{r['mapped_km2']:,.0f} km² mapped). " + r["note"])]
    m = _map(ctx, r["output"], "Snow and ice (NDSI)", r["labels"])
    if m:
        blocks.append(("fig", m, "Snow and ice map"))
    return blocks, ["hall"]


def _b_zone(ctx, a, r):
    t = _df(r["zones"], max_rows=30)
    txt = f"Class areas of {r['layer']} were summarised by elevation zone of {r['dem']}."
    if r.get("snowline_50pct_m"):
        txt += f" {r['focus_class']} covers half of the zone area from about {r['snowline_50pct_m']:,.0f} m upwards."
    return [("p", txt), ("table", t.iloc[:, :12], "Class area (km²) and share (%) by elevation zone")], []


def _b_comp(ctx, a, r):
    t = pd.DataFrame(r.get("scenes_table", [])).head(20)
    blocks = [("p", f"A cloud-masked {r.get('product')} composite was built from the {len(r['scenes_used'])} least-cloudy of {r['scenes_found']} scenes "
                    f"(Microsoft Planetary Computer) on a {r['resolution_m']:.0f} m grid ({r['crs']}). Clouds, cloud shadows and cirrus were masked per pixel "
                    "before taking the per-band median of surface reflectance; "
                    f"{r.get('clear_pct', r['pixels_with_data_pct']):.1f}% of the area has at least one clear observation (mean {r['mean_observations']:.1f})."
                    + (f" A further {r['gap_filled_pct']:.1f}% was rejected by the cloud mask in every scene (typically glacier ice and high peaks "
                       "that Fmask confuses with cloud or cirrus) and was filled with the median of all valid observations."
                       if r.get("gap_filled_pct", 0) >= 0.05 else ""))]
    if len(t):
        blocks.append(("table", t, "Scenes considered for the composite (least cloudy first)"))
    return blocks, []


def _b_dem(ctx, a, r):
    return [("p", f"Elevation came from the Copernicus DEM GLO-30 ({r['min_m']:.0f}-{r['max_m']:.0f} m in the study area). " + r["note"])], []


def _b_wc(ctx, a, r):
    t = pd.DataFrame({"class": list(r["class_area_ha"]), "area_ha": list(r["class_area_ha"].values())})
    return [("p", r["note"]), ("table", t, f"ESA WorldCover {r['year']} land cover in the study area")], []



def _b_indices(ctx, a, r):
    t = _df(r["indices"], ["index", "reference", "min", "mean", "max"])
    return [("p", f"Spectral indices ({', '.join(t['index'])}) were computed from surface reflectance obtained as DN × {r['scale']} + {r['offset']}."),
            ("table", t, "Spectral indices and their value ranges")], []


def _b_classify(ctx, a, r):
    cv = r["cross_validation"]
    blocks = [("p", f"Land cover was classified with a {r['model']} classifier using {len(r['features'])} features "
                    f"({', '.join(r['features'][:12])}{'…' if len(r['features']) > 12 else ''}) sampled at {r['training_pixels']:,} training pixels "
                    f"(per class: {', '.join(f'{k}: {v}' for k, v in r['per_class_training'].items())}). Duplicate samples within one pixel were removed. "
                    "Accuracy was estimated by random stratified k-fold cross-validation and by spatial cross-validation in which samples are grouped "
                    "in blocks" + (" or by training polygon" if "polygon_group_kfold" in cv else "") + ", because random folds overestimate accuracy when "
                    "neighbouring, autocorrelated samples fall in both training and test folds.")]
    rows = []
    for k, lab in (("random_kfold", "Random stratified k-fold"), ("spatial_block_kfold", "Spatial block k-fold"), ("polygon_group_kfold", "Polygon-grouped k-fold")):
        if k in cv:
            rows.append(dict(validation=lab, folds=cv[k]["folds"], overall_accuracy=cv[k]["overall_accuracy"], kappa=cv[k]["kappa"], macro_F1=cv[k]["macro_f1"]))
    blocks.append(("table", pd.DataFrame(rows), "Cross-validated accuracy of the classifier"))
    sp = cv.get("polygon_group_kfold") or cv.get("spatial_block_kfold") or cv.get("random_kfold")
    if sp:
        blocks.append(("table", pd.DataFrame({"class": sp["classes"], "producer's accuracy": sp["producers_accuracy"], "user's accuracy": sp["users_accuracy"],
                                              "F1": sp["f1"]}), "Per-class accuracy (spatially grouped cross-validation)"))
    if "optimism_gap_oa" in cv:
        blocks.append(("p", f"Random cross-validation was {100 * cv['optimism_gap_oa']:+.1f} percentage points more optimistic than spatial block cross-validation; "
                            "the spatial figure is reported as the map's expected accuracy."))
    imp = r.get("feature_importance", [])[:12]
    if imp:
        blocks.append(("fig", _barh([d["feature"] for d in imp], [d["importance"] for d in imp], "Permutation importance (drop in accuracy)"),
                       "Most important features (permutation importance)"))
    pr = r.get("prediction")
    if pr:
        m = _map(ctx, pr["output"], f"Classified land cover ({r['model']})", a.get("labels"))
        if m:
            blocks.append(("fig", m, f"Classified land-cover map {pr['output']}"))
        if pr.get("mean_confidence") is not None:
            blocks.append(("p", f"The mean classifier confidence was {pr['mean_confidence']:.2f}; {100 * pr['low_confidence_share']:.1f}% of pixels had a "
                                "maximum class probability below 0.5."))
    return blocks, ["breiman", "roberts", "ploton"]


def _b_aaa(ctx, a, r):
    ct = _df(r["classes"])
    blocks = [("p", r["methods_text"].replace("\n\n", " ")), ("table", ct, "Area-adjusted accuracy and error-adjusted class areas (95% confidence intervals)")]
    u = r["area_unit"]
    mcol, acol, ccol = f"mapped area ({u})", f"adjusted area ({u})", f"± 95% CI ({u})"
    if {mcol, acol, ccol} <= set(ct.columns):
        fig, ax = plt.subplots(figsize=(6.4, 0.4 * len(ct) + 1.2))
        y = np.arange(len(ct))
        ax.barh(y, ct[mcol], color="#C4B5FD", label="mapped (pixel count)")
        ax.errorbar(ct[acol], y, xerr=ct[ccol], fmt="o", color="#BE185D", label="error-adjusted ± 95% CI")
        ax.set_yticks(y, ct["class"].astype(str), fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel(f"Area ({u})")
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        blocks.append(("fig", _png(fig), "Mapped versus error-adjusted class areas"))
    return blocks, ["olofsson", "pontius2011", "pontius2014"]


def _b_design(ctx, a, r):
    return [("p", f"An accuracy-assessment sample was designed for {r['raster']} following Olofsson et al. (2014): {r['n_total_formula']} points for the target "
                  f"standard error, {r['n_allocated']} after allocation to strata."), ("table", _df(r["design"]), "Stratified sample design")], ["olofsson"]


def _b_acc(ctx, a, r):
    return [("p", f"A conventional confusion-matrix assessment of {a.get('raster')} with {r.get('n')} validation points gave an overall accuracy of "
                  f"{_fmt(r['overall_accuracy'])} and kappa of {_fmt(r['kappa'])}.")], ["pontius2011"]


def _b_trans(ctx, a, r):
    m = pd.DataFrame(r["matrix_ha"], index=[f"from {c}" for c in r["classes"]], columns=[f"to {c}" for c in r["classes"]]).reset_index()
    return [("p", f"The transition matrix between {a.get('old_layer')} and {a.get('new_layer')} shows {r['persistence_percent']:.1f}% persistence."),
            ("table", m, "Transition matrix (ha)")], []


def _b_ia(ctx, a, r):
    iv = _df(r["interval"], ["interval", "change_area", "change_pct_extent", "S_annual_pct", "U_uniform_pct", "speed"])
    cat = _df(r["category"], ["interval", "category", "gross_gain", "gross_loss", "net_change", "swap", "G_gain_intensity", "gain_status",
                              "L_loss_intensity", "loss_status"], 60)
    blocks = [("p", r["methods_text"].replace("\n\n", " ")), ("table", iv, "Interval-level intensity analysis"),
              ("fig", _barh(list(iv["interval"]), list(iv["S_annual_pct"]), "Annual change (% of area per year)", ref=r["uniform_intensity_pct_per_year"],
                            ref_label="uniform intensity"), "Interval-level change intensity"),
              ("table", cat, "Category-level gains and losses")]
    comp = _df(r["components"])
    if len(comp):
        blocks.append(("table", comp, "Change components and alternation per category"))
    return blocks, ["aldwaik", "pontius2017"]


def _b_freq(ctx, a, r):
    m = _map(ctx, r["output"], "Number of changes per pixel")
    return ([("fig", m, "Change frequency")] if m else []) + [("p", r["note"])], ["pontius2017"]


def _b_traj(ctx, a, r):
    t = pd.DataFrame({"trajectory": list(r["area_by_trajectory"]), f"area ({r['area_unit']})": list(r["area_by_trajectory"].values())})
    return [("table", t, f"Trajectories of class {r['category']}")], ["pontius2017"]


def _b_lm(ctx, a, r):
    land = pd.DataFrame(r["landscape"]).set_index("layer").T.reset_index().rename(columns={"index": "metric"})
    cls = _df(r["classes"], ["layer", "class_name", "PLAND", "NP", "PD", "LPI", "ED_m_per_ha", "AREA_MN_ha", "SHAPE_MN", "ENN_MN_m", "AI", "COHESION"], 60)
    return [("p", f"Landscape pattern was quantified with FRAGSTATS definitions ({r['neighbourhood']}-neighbour patch rule) for {', '.join(r['layers'])}. "
                  + r["interpretation"]), ("table", land, "Landscape-level metrics"), ("table", cls, "Class-level metrics")], ["fragstats"]


def _b_hs(ctx, a, r):
    gm = r["global_moran"]
    blocks = [("p", f"Spatial clustering of {r['variable']} was tested on {r['analysis_cell_size']:.0f} m blocks ({r['valid_cells']:,} cells, {r['neighbourhood']}). "
                    f"Global Moran's I was {_fmt(gm['I'])} (z = {_fmt(gm['z'], 2)}, p = {_fmt(gm['p'], 4)}). " + r["note"])]
    refs = ["getis", "anselin"]
    if "gi_star" in r:
        gi = r["gi_star"]
        blocks.append(("table", pd.DataFrame({"Gi* bin": list(gi["cells_by_bin"]), "cells": list(gi["cells_by_bin"].values())}), "Getis-Ord Gi* hot and cold spots"))
        name = next((o for o in r["outputs"] if o.endswith("_gi_bins.tif")), None)
        m = _map(ctx, name, "Getis-Ord Gi* hot and cold spots", {str(k): v for k, v in
                                                                   {3: "hot 99%", 2: "hot 95%", 1: "hot 90%", 0: "not significant", -1: "cold 90%",
                                                                    -2: "cold 95%", -3: "cold 99%"}.items()}) if name else None
        if m:
            blocks.append(("fig", m, "Gi* hot and cold spots"))
        if gi.get("fdr_corrected"):
            refs.append("bh")
    if "lisa" in r and "cells_by_cluster" in r["lisa"]:
        blocks.append(("table", pd.DataFrame({"LISA cluster": list(r["lisa"]["cells_by_cluster"]), "cells": list(r["lisa"]["cells_by_cluster"].values())}),
                       "Local Moran's I clusters"))
    return blocks, refs


def _b_mw(ctx, a, r):
    m = _map(ctx, r["output"], f"Moving-window {r['metric']} ({r['window_m']:.0f} m window)")
    return ([("fig", m, f"Moving-window {r['metric']}")] if m else []), ["fragstats"]


def _b_drv(ctx, a, r):
    sc = pd.DataFrame(r["screening"])
    blocks = [("p", "Candidate drivers were screened for each major transition with Cramér's V on decile-binned drivers and the area under the ROC curve. "
                    "Multicollinearity was checked with variance inflation factors. " + r["note"])]
    if len(sc):
        blocks.append(("table", sc.pivot(index="driver", columns="transition", values="auc").round(3).reset_index(), "Driver AUC per transition"))
        blocks.append(("table", sc.pivot(index="driver", columns="transition", values="cramers_v").round(3).reset_index(), "Driver Cramér's V per transition"))
    blocks.append(("table", pd.DataFrame({"driver": list(r["vif"]), "VIF": list(r["vif"].values())}), "Variance inflation factors"))
    return blocks, ["cramer"]


def _b_sim(ctx, a, r):
    s = r["simulation"]
    blocks = [("p", f"Land change was simulated with a Markov-cellular automaton model calibrated on {s['calibration']}. Transition potentials were modelled with "
                    f"{s['model']} using drivers {', '.join(s['drivers'])}; quantities came from the Markov matrix projected over {s['markov_matrix']['years']} years; "
                    f"change was allocated iteratively with a neighbourhood effect. Scenario: {s['scenario']} (target year {s['target_year']}, start map {s['start_map']}). "
                    f"The modelled transitions covered {100 * (s['share_of_calibration_change_modelled'] or 0):.0f}% of calibration change."),
              ("table", _df(s["transitions_modelled"]), "Modelled transitions and hold-out AUC of the potential models"),
              ("table", _df(s["area_table"]), f"Area by class, start versus simulated {s['target_year']} (ha)")]
    m = _map(ctx, s["output"], f"Simulated land cover {s['target_year']} ({s['scenario']})")
    if m:
        blocks.append(("fig", m, f"Simulated land cover, {s['scenario']}"))
    refs = ["markov"]
    if r.get("validation"):
        b2, r2 = _b_val(ctx, {}, r["validation"])
        blocks += b2
        refs += r2
    return blocks, refs


def _b_val(ctx, a, r):
    t = _df(r["results"], ["model", "fom", "kappa_simulation", "hits", "misses", "wrong_hits", "false_alarms", "quantity_disagreement", "allocation_disagreement"])
    return [("p", f"Simulated maps were validated against {r['observed']} starting from {r['initial']} ({r['compared_pixels']:,} pixels). " + r["note"]),
            ("table", t, "Hindcast validation: figure of merit, Kappa simulation and disagreement components")], ["fom", "vanvliet", "pontius2011"]


def _b_hind(ctx, a, r):
    d = r.get("disagreement", {})
    txt = (f"The simulated map {a.get('simulated')} agreed with {a.get('observed')} for {100 * r['overall_accuracy']:.1f}% of pixels (kappa {_fmt(r['kappa'])}; "
           f"quantity disagreement {_fmt(d.get('quantity'))}, allocation disagreement {_fmt(d.get('allocation'))}).")
    if r.get("figure_of_merit"):
        txt += f" Figure of merit: {_fmt(r['figure_of_merit'].get('fom'))}."
    return [("p", txt)], ["fom", "pontius2011"]


def _b_lookup(ctx, a, r):
    t = pd.DataFrame({"class": list(r["lookup"]), "SWAT+ code": list(r["lookup"].values())})
    return [("p", "LULC classes were translated to SWAT+ land-use codes for QSWAT+ (lookup table below)."), ("table", t, "LULC to SWAT+ land-use lookup")], ["swat"]


def _b_cn(ctx, a, r):
    return [("p", f"Direct runoff was estimated with the SCS Curve Number method (soil groups: {r['hsg']}; Ia = {r['initial_abstraction_ratio']} S"
                  + ("; CN2 adjusted for slope as in SWAT" if r["slope_adjusted"] else "") + ") for each land-cover map under identical rainfall. " + r["note"]),
            ("table", _df(r["results"]), "Curve Number runoff by land-cover scenario")], ["tr55", "swat"]


def _b_rusle(ctx, a, r):
    t = _df(r["results"])
    blocks = [("p", f"Mean annual soil loss was estimated with RUSLE (R = {r['R']}, K = {r['K']}, P = {r['P']}, LS by {r['ls_method'].replace('_', ' ')}, mean LS "
                    f"{_fmt(r['mean_LS'], 2)}), with C factors from the SWAT+ land-use code. " + r["note"]), ("table", t, "RUSLE soil loss by land-cover scenario")]
    first = next((o for o in r["outputs"] if o.endswith("_soil_loss.tif")), None)
    m = _map(ctx, first, "RUSLE soil loss (t ha⁻¹ yr⁻¹)") if first else None
    if m:
        blocks.append(("fig", m, "Soil loss map"))
    return blocks, ["rusle"]


def _b_flow(ctx, a, r):
    rows = []
    for p in ("calibration", "validation", "all"):
        if p in r:
            s = r[p]
            rows.append(dict(period=p, n=s["n"], NSE=s["nse"], KGE=s["kge"], R2=s["r2"], PBIAS=s["pbias_percent"], RSR=s["rsr"], FHV=s["pbias_fhv"],
                             FLV=s["pbias_flv"], FMS=s["pbias_fms"], rating=f"NSE {s['ratings']['nse']}, PBIAS {s['ratings']['pbias_percent']}"))
    f = r["fdc"]
    return [("p", f"Simulated streamflow was evaluated at a {r['step']} step for {r['period']}. " + r["note"]),
            ("table", pd.DataFrame(rows), "Streamflow performance and Moriasi et al. ratings"),
            ("fig", _lines(f["exceedance"], {"observed": f["obs"], "simulated": f["sim"]}, "Exceedance probability", "Flow", logy=True), "Flow-duration curves")], \
        ["moriasi2015", "moriasi2007", "yilmaz", "gupta"]


def _b_hydro(ctx, a, r):
    return [("p", f"Streamflow performance over {r['first']} to {r['last']} ({r['n_pairs']} pairs): NSE {_fmt(r['nse'])}, PBIAS {_fmt(r['pbias_percent'], 1)}%, "
                  f"R² {_fmt(r['r2'])}, KGE {_fmt(r['kge'])}.")], ["moriasi2015", "gupta"]


def _b_attr(ctx, a, r):
    t = pd.DataFrame([dict(metric="mean flow", change_pct=r["mean_change_pct"]), dict(metric="high flow Q5", change_pct=r["Q5_change_pct"]),
                      dict(metric="median Q50", change_pct=r["Q50_change_pct"]), dict(metric="low flow Q95", change_pct=r["Q95_change_pct"])])
    f = r["fdc"]
    return [("p", r["note"]), ("table", t, "Hydrological response to the land-cover change (scenario versus baseline run)"),
            ("fig", _lines(f["exceedance"], {"baseline": f["baseline"], "scenario": f["scenario"]}, "Exceedance probability", "Flow", logy=True),
             "Flow-duration curves of baseline and scenario runs")], ["swat"]


def _b_zonal(ctx, a, r):
    return [("table", _df(r["preview"], max_rows=30), f"Zonal statistics of {a.get('raster')} by {a.get('vector')}")], []


SECTIONS = [
    ("Data acquisition", ["download_composite", "download_dem", "download_worldcover"]),
    ("Basin topography, snow and ice", ["hypsometry", "map_snow_cover", "elevation_zone_statistics"]),
    ("Image classification", ["spectral_indices", "classify_image", "cluster_image"]),
    ("Accuracy assessment", ["design_accuracy_sample", "area_adjusted_accuracy", "accuracy_assessment"]),
    ("Land-cover change", ["transition_matrix", "intensity_analysis", "change_frequency_raster", "trajectory_raster"]),
    ("Landscape pattern and hotspots", ["landscape_metrics", "moving_window_map", "hotspot_analysis"]),
    ("Drivers and scenario simulation", ["driver_analysis", "simulate_lulc", "validate_simulation", "hindcast_validation"]),
    ("Hydrological and erosion response", ["swat_landuse_lookup", "curve_number_runoff", "rusle_erosion", "flow_evaluation", "hydro_metrics",
                                           "lulc_flow_attribution"]),
    ("Zonal summaries", ["zonal_statistics"]),
]
BUILDERS = {"hypsometry": _b_hyps, "map_snow_cover": _b_snow, "elevation_zone_statistics": _b_zone, "download_composite": _b_comp, "download_dem": _b_dem, "download_worldcover": _b_wc, "spectral_indices": _b_indices, "classify_image": _b_classify, "area_adjusted_accuracy": _b_aaa, "design_accuracy_sample": _b_design,
            "accuracy_assessment": _b_acc, "transition_matrix": _b_trans, "intensity_analysis": _b_ia, "change_frequency_raster": _b_freq,
            "trajectory_raster": _b_traj, "landscape_metrics": _b_lm, "moving_window_map": _b_mw, "hotspot_analysis": _b_hs, "driver_analysis": _b_drv,
            "simulate_lulc": _b_sim, "validate_simulation": _b_val, "hindcast_validation": _b_hind, "swat_landuse_lookup": _b_lookup,
            "curve_number_runoff": _b_cn, "rusle_erosion": _b_rusle, "flow_evaluation": _b_flow, "hydro_metrics": _b_hydro,
            "lulc_flow_attribution": _b_attr, "zonal_statistics": _b_zonal}


def available(ctx, latest_only=True):
    """Analyses that can go into a report: list of (index, label)."""
    res = ctx.__dict__.get("results", [])
    items = [(i, x) for i, x in enumerate(res) if x["tool"] in BUILDERS and "error" not in x["result"]]
    if latest_only:
        seen, keep = set(), []
        for i, x in reversed(items):
            key = (x["tool"], str(x["result"].get("output") or (x["result"].get("simulation") or {}).get("output") or x["args"].get("raster")
                                  or x["args"].get("layers") or x["args"].get("layer") or ""))
            if key not in seen:
                seen.add(key)
                keep.append((i, x))
        items = list(reversed(keep))
    return [(i, f"{x['time'][11:19]} · {x['tool']} · " + ", ".join(f"{k}={str(v)[:30]}" for k, v in list(x["args"].items())[:2])) for i, x in items]


def _inventory(ctx):
    rows = []
    for n in ctx.store.rasters:
        r = ctx.store.rasters[n]
        rows.append(dict(type="raster", name=n, detail=f"{r.data.shape[1]}×{r.data.shape[0]} px, {abs(r.transform.a):g} units, "
                                                     f"{r.crs.to_string() if r.crs else 'no CRS'}" + (f", {r.bands.shape[0]} bands" if r.bands is not None else "")))
    for n, t in ctx.tables.items():
        rows.append(dict(type="table", name=n, detail=f"{len(t):,} rows × {t.shape[1]} columns"))
    for n, g in ctx.__dict__.get("vectors", {}).items():
        rows.append(dict(type="vector", name=n, detail=f"{len(g):,} features, {', '.join(sorted(g.geom_type.unique()))}"))
    return pd.DataFrame(rows)


def build(ctx, meta, selection=None, include_log=True, version=""):
    """Return a list of blocks: ('title'|'h1'|'h2'|'p'|'table'|'fig'|'refs', ...)."""
    res = ctx.__dict__.get("results", [])
    chosen = set(selection) if selection is not None else {i for i, _ in available(ctx)}
    _LABELS.clear()
    for x in res:  # class names given anywhere in the session label every map
        if isinstance(x["args"].get("labels"), dict):
            _LABELS.update({str(k): v for k, v in x["args"]["labels"].items() if v})
    blocks = [("title", meta)]
    if meta.get("abstract"):
        blocks += [("h1", "Summary"), ("p", meta["abstract"])]
    inv = _inventory(ctx)
    blocks += [("h1", "Data"), ("p", "The following inputs were analysed in this session. All statistics below were produced by the audited tools of the "
                                     f"LULC-MOLUSCE-SWAT+ Agent v{version} and are recorded in the processing log (Appendix).")]
    if len(inv):
        blocks.append(("table", inv, "Input data"))
    refs = []
    for title, tools in SECTIONS:
        sec = []
        for i, x in enumerate(res):
            if i in chosen and x["tool"] in tools:
                try:
                    b, rf = BUILDERS[x["tool"]](ctx, x["args"], x["result"])
                except Exception as e:  # never let one section break the report
                    b, rf = [("p", f"[{x['tool']} could not be summarised: {type(e).__name__}: {e}]")], []
                sec += b
                refs += rf
        if sec:
            blocks += [("h1", title)] + sec
    blocks.append(("h1", "Limitations"))
    blocks.append(("p", "Results depend on input quality, class definitions and the parameters listed above. Simulated maps are scenarios, not forecasts. "
                        "Curve Number and RUSLE estimates compare land-cover scenarios under identical conditions and do not replace a calibrated SWAT+ "
                        "water and sediment balance. Every number should be checked against the processing log before publication."))
    if refs:
        blocks.append(("refs", sorted({REFS[k] for k in refs if k in REFS})))
    if include_log:
        log = ctx.log_df()
        if len(log):
            blocks += [("h1", "Appendix: processing log"), ("table", log[["date", "input", "parameters", "output"]].tail(80), "Processing log")]
    return blocks


# ------------------------------------------------------------------ renderers
def _cell(v):
    if isinstance(v, float):
        return _fmt(v)
    if isinstance(v, (list, dict)):
        return str(v)[:60]
    v = str(v)
    return v if len(v) <= 160 else v[:157] + "…"


def to_docx(blocks):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    nt = nf = 0
    for b in blocks:
        kind = b[0]
        if kind == "title":
            m = b[1]
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(m.get("title", "Land-cover change report"))
            run.bold = True
            run.font.size = Pt(20)
            for line in (m.get("study_area"), m.get("author"), m.get("institution"), m.get("date")):
                if line:
                    q = doc.add_paragraph(line)
                    q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif kind == "h1":
            doc.add_heading(b[1], level=1)
        elif kind == "h2":
            doc.add_heading(b[1], level=2)
        elif kind == "p":
            doc.add_paragraph(b[1])
        elif kind == "table":
            df, cap = b[1], b[2]
            nt += 1
            c = doc.add_paragraph()
            c.add_run(f"Table {nt}. ").bold = True
            c.add_run(cap)
            df = df.iloc[:, :12]
            t = doc.add_table(rows=1, cols=len(df.columns))
            t.style = "Light Grid Accent 1"
            for j, col in enumerate(df.columns):
                t.rows[0].cells[j].text = str(col)
            for row in df.astype(object).itertuples(index=False):
                cells = t.add_row().cells
                for j, v in enumerate(row):
                    cells[j].text = _cell(v)
            for row in t.rows:
                for cell in row.cells:
                    for par in cell.paragraphs:
                        for run in par.runs:
                            run.font.size = Pt(8)
            doc.add_paragraph()
        elif kind == "fig" and b[1]:
            nf += 1
            doc.add_picture(io.BytesIO(b[1]), width=Inches(6.3))
            c = doc.add_paragraph()
            c.add_run(f"Figure {nf}. ").bold = True
            c.add_run(b[2])
        elif kind == "refs":
            doc.add_heading("References", level=1)
            for ref in b[1]:
                doc.add_paragraph(ref)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


CSS = """body{font-family:Georgia,'Times New Roman',serif;max-width:860px;margin:32px auto;padding:0 20px;color:#111;line-height:1.5}
h1.t{font-size:28px;text-align:center;margin-bottom:4px}.meta{text-align:center;color:#444}h2{border-bottom:2px solid #7C3AED;padding-bottom:3px;margin-top:34px}
table{border-collapse:collapse;width:100%;font:12px/1.35 Arial,sans-serif;margin:6px 0 18px}th,td{border:1px solid #ccc;padding:3px 6px;text-align:left}
th{background:#F3E8FF}caption{caption-side:top;text-align:left;font:bold 12px Arial,sans-serif;margin-bottom:4px}
figure{margin:12px 0 22px}figure img{width:100%}figcaption{font:12px Arial,sans-serif;color:#333}.refs p{font-size:13px;padding-left:2em;text-indent:-2em;margin:4px 0}
@media print{body{margin:0;max-width:none}h2{page-break-after:avoid}figure,table{page-break-inside:avoid}}"""


def to_html(blocks):
    out = ["<!doctype html><html><head><meta charset='utf-8'><title>Report</title><style>", CSS, "</style></head><body>"]
    nt = nf = 0
    for b in blocks:
        kind = b[0]
        if kind == "title":
            m = b[1]
            out.append(f"<h1 class='t'>{html.escape(m.get('title', 'Land-cover change report'))}</h1>")
            out.append("<p class='meta'>" + "<br>".join(html.escape(x) for x in (m.get("study_area"), m.get("author"), m.get("institution"), m.get("date")) if x) + "</p>")
        elif kind in ("h1", "h2"):
            out.append(f"<h2>{html.escape(b[1])}</h2>")
        elif kind == "p":
            out.append(f"<p>{html.escape(b[1])}</p>")
        elif kind == "table":
            nt += 1
            df = b[1]
            out.append(f"<table><caption>Table {nt}. {html.escape(b[2])}</caption><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns) + "</tr>")
            for row in df.astype(object).itertuples(index=False):
                out.append("<tr>" + "".join(f"<td>{html.escape(_cell(v))}</td>" for v in row) + "</tr>")
            out.append("</table>")
        elif kind == "fig" and b[1]:
            nf += 1
            out.append(f"<figure><img src='data:image/png;base64,{base64.b64encode(b[1]).decode()}'><figcaption><b>Figure {nf}.</b> {html.escape(b[2])}</figcaption></figure>")
        elif kind == "refs":
            out.append("<h2>References</h2><div class='refs'>" + "".join(f"<p>{html.escape(r)}</p>" for r in b[1]) + "</div>")
    out.append("</body></html>")
    return "".join(out).encode()


def generate(ctx, title="Land-cover change, simulation and hydrological response", author="", institution="", study_area="", abstract="",
             selection=None, include_log=True, version=""):
    meta = dict(title=title, author=author, institution=institution, study_area=study_area, abstract=abstract,
                date=datetime.date.today().strftime("%d %B %Y"))
    blocks = build(ctx, meta, selection, include_log, version)
    return blocks, to_docx(blocks), to_html(blocks)
