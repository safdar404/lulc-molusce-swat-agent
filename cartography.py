"""Cartographic map composer: title, map frame with grid coordinates, legend, scale bar, north arrow and a metadata box.

Pure matplotlib (Agg backend), no QGIS needed. Works for classified (LULC, change, disagreement) and continuous
(spectral index, DEM, single band) rasters, plus RGB satellite composites.
"""
import datetime
import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import numpy as np  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.patches import FancyArrow, Patch, Rectangle  # noqa: E402

# Conventional LULC colours, matched on class names (any language-neutral keyword hit wins).
LULC_KEYWORDS = [
    # hotspot (Gi*) and LISA classes, so statistical maps get a diverging scheme
    (("hot 99",), "#B2182B"), (("hot 95",), "#EF8A62"), (("hot 90",), "#FDDBC7"), (("not significant",), "#F0F0F0"),
    (("cold 90",), "#D1E5F0"), (("cold 95",), "#67A9CF"), (("cold 99",), "#2166AC"),
    (("high-high",), "#D7191C"), (("low-low",), "#2C7BB6"), (("high-low",), "#FDAE61"), (("low-high",), "#ABD9E9"),
    (("water", "river", "lake", "reservoir", "sea"), "#2B7BB9"),
    (("built", "urban", "settlement", "impervious", "city", "road"), "#D7301F"),
    (("forest", "tree", "woodland"), "#1A7A35"),
    (("shrub", "scrub", "bush"), "#8DB360"),
    (("grass", "pasture", "range", "meadow"), "#B8D97A"),
    (("crop", "agri", "farm", "cultiv"), "#F2C94C"),
    (("bare", "barren", "soil", "sand", "rock", "desert"), "#C9A27E"),
    (("snow", "ice", "glacier"), "#E8F4FA"),
    (("wetland", "marsh", "swamp"), "#5FB3B3"),
    (("cloud",), "#BDBDBD"),
]
FALLBACK = ["#1A7A35", "#F2C94C", "#D7301F", "#2B7BB9", "#C9A27E", "#8DB360", "#9C27B0", "#5FB3B3",
            "#FF8F00", "#795548", "#E91E63", "#607D8B", "#B8D97A", "#3F51B5", "#CDDC39", "#00BCD4"]
CONTINUOUS = {"NDVI": "RdYlGn", "NDWI": "BrBG", "NDBI": "RdGy_r", "DEM": "terrain", "Single band": "viridis"}

MAP_KINDS = ["LULC (classified)", "Change / transition", "Disagreement", "Spectral index", "Continuous", "RGB composite"]


def class_colours(classes, labels=None):
    labels = labels or {}
    out, used = {}, 0
    for c in classes:
        name = str(labels.get(str(c), "")).lower()
        hit = next((col for keys, col in LULC_KEYWORDS if any(k in name for k in keys)), None)
        if hit is None:
            hit = FALLBACK[used % len(FALLBACK)]
            used += 1
        out[c] = hit
    return out


def categorical_colours(kind, classes, labels=None):
    """Colours and (completed) labels for classified, change (old*10+new) and disagreement rasters."""
    labels = dict(labels or {})
    classes = [int(c) for c in classes]
    if kind == "Disagreement":
        labels = {"0": "Agreement", "1": "Disagreement", **labels}
        return {c: ("#E0E0E0" if c == 0 else "#D7301F") for c in classes}, labels
    if kind == "Change / transition":
        base = class_colours(sorted({c % 10 for c in classes}), labels.get("_base"))
        cols = {}
        for c in classes:
            if c // 10 == c % 10:
                cols[c] = "#E6E6E6"
                labels.setdefault(str(c), f"No change ({c % 10})")
            else:
                cols[c] = base.get(c % 10, "#999999")
                labels.setdefault(str(c), f"{c // 10} → {c % 10}")
        return cols, labels
    return class_colours(classes, labels), labels


def guess_kind(arr, mask, name=""):
    n = name.lower()
    if arr.ndim == 3:
        return "RGB composite"
    if "disagree" in n:
        return "Disagreement"
    if "transition" in n or "change" in n:
        return "Change / transition"
    if any(k in n for k in ("ndvi", "ndwi", "ndbi")):
        return "Spectral index"
    v = arr[~mask]
    if arr.dtype.kind in "iu" and v.size and np.unique(v).size <= 40:
        return "LULC (classified)"
    return "Continuous"


def downsample(arr, mask, max_px=1400):
    """Stride-based decimation for display only (statistics always use full resolution)."""
    h, w = mask.shape
    s = max(1, int(math.ceil(max(h, w) / max_px)))
    return (arr[..., ::s, ::s] if arr.ndim == 3 else arr[::s, ::s]), mask[::s, ::s], s


def stretch(band, mask, lo=2, hi=98):
    v = band[~mask]
    if not v.size:
        return np.zeros(band.shape, "float32")
    a, b = np.percentile(v, [lo, hi])
    return np.clip((band.astype("float32") - a) / ((b - a) or 1), 0, 1)


# ---------------- scale bar / grid helpers ----------------
def _nice(x):
    e = 10 ** math.floor(math.log10(x))
    return max(m * e for m in (1, 2, 2.5, 5, 10) if m * e <= x)


def metres_per_unit(crs, lat=0.0):
    """Ground metres per map unit along x. Geographic CRS uses the local length of one degree of longitude."""
    if crs is not None and crs.is_geographic:
        return 111320.0 * math.cos(math.radians(lat))
    if crs is not None and crs.linear_units_factor:
        try:
            return float(crs.linear_units_factor[1])
        except Exception:
            pass
    return 1.0


def _fmt_coord(v, geographic, axis):
    if geographic:
        hemi = ("E" if v >= 0 else "W") if axis == "x" else ("N" if v >= 0 else "S")
        d = abs(v)
        return f"{int(d)}°{int(round((d % 1) * 60)):02d}′{hemi}"
    return f"{v:,.0f}"


def draw_scalebar(ax, extent, crs, fig_units_frac=0.28):
    x0, x1, y0, y1 = extent
    mpu = metres_per_unit(crs, (y0 + y1) / 2)
    ground_w = (x1 - x0) * mpu
    length_m = _nice(ground_w * fig_units_frac)
    unit, div = ("km", 1000.0) if length_m >= 1000 else ("m", 1.0)
    segs = 4
    seg_map = length_m / mpu / segs
    bx, by = x0 + (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.05
    bh = (y1 - y0) * 0.012
    pad = (x1 - x0) * 0.012
    ax.add_patch(Rectangle((bx - pad, by - bh * 2.2), seg_map * segs + 3.5 * pad, bh * 5.6, fc="white", ec="#555", lw=0.5, alpha=0.88, zorder=8))
    for i in range(segs):
        ax.add_patch(Rectangle((bx + i * seg_map, by), seg_map, bh, fc="black" if i % 2 == 0 else "white", ec="black", lw=0.6, zorder=9))
    for i in (0, segs // 2, segs):
        val = length_m * i / segs / div
        ax.text(bx + i * seg_map, by + bh * 1.4, f"{val:g}" + (f" {unit}" if i == segs else ""), ha="center", va="bottom", fontsize=7, zorder=10)
    return length_m


def draw_north_arrow(ax, extent):
    x0, x1, y0, y1 = extent
    w, h = x1 - x0, y1 - y0
    cx, cy = x1 - w * 0.06, y1 - h * 0.16
    L = h * 0.08
    ax.add_patch(Rectangle((cx - w * 0.03, cy - L * 0.25), w * 0.06, L * 1.85, fc="white", ec="#555", lw=0.5, alpha=0.88, zorder=8))
    ax.add_patch(FancyArrow(cx, cy, 0, L, width=w * 0.012, head_width=w * 0.032, head_length=L * 0.45, length_includes_head=True,
                            fc="black", ec="black", zorder=9))
    ax.text(cx, cy + L * 1.12, "N", ha="center", va="bottom", fontsize=10, fontweight="bold", zorder=10)


# ---------------- main composer ----------------
def compose_map(arr, mask, transform, crs, *, kind=None, title="Map", subtitle="", labels=None, layer_name="",
                index_name=None, cmap=None, vmin=None, vmax=None, author="", source="", show_grid=True,
                show_north=True, show_scale=True, legend_stats=True, max_legend=18, version=""):
    """Return a matplotlib Figure laid out as a finished map (A4-landscape proportions)."""
    kind = kind or guess_kind(arr, mask, layer_name)
    pixel_area = abs(transform.a * transform.e)
    full_mask = mask
    disp, dmask, step = downsample(arr, mask)
    h, w = full_mask.shape
    x0, y1 = transform.c, transform.f
    x1, y0 = x0 + transform.a * w, y1 + transform.e * h
    extent = (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1))
    geographic = bool(crs is not None and crs.is_geographic)

    fig = plt.figure(figsize=(11.69, 8.27), dpi=100, facecolor="white")
    ax = fig.add_axes([0.05, 0.10, 0.64, 0.76])
    lax = fig.add_axes([0.72, 0.34, 0.26, 0.52])
    lax.axis("off")
    iax = fig.add_axes([0.72, 0.10, 0.26, 0.21])
    iax.axis("off")

    fig.text(0.05, 0.945, title, fontsize=18, fontweight="bold", color="#1b1b1b")
    if subtitle:
        fig.text(0.05, 0.905, subtitle, fontsize=11, color="#444")

    legend_items, cbar = [], None
    if kind == "RGB composite":
        rgb = np.dstack([stretch(disp[i], dmask) for i in range(3)])
        rgba = np.dstack([rgb, (~dmask).astype("float32")])
        ax.imshow(rgba, extent=extent, interpolation="nearest")
        legend_items = [Patch(fc="#d33", label="Red channel: " + str((labels or {}).get("r", "band 1"))),
                        Patch(fc="#3a3", label="Green channel: " + str((labels or {}).get("g", "band 2"))),
                        Patch(fc="#33d", label="Blue channel: " + str((labels or {}).get("b", "band 3"))),
                        Patch(fc="white", ec="#888", label="2–98 % linear stretch")]
    elif kind in ("LULC (classified)", "Change / transition", "Disagreement"):
        v = arr[~full_mask]
        classes, counts = np.unique(v, return_counts=True)
        cols, labels = categorical_colours(kind, classes.tolist(), labels)
        cl = classes.tolist()
        lut = ListedColormap([cols[c] for c in cl])
        bounds = np.concatenate([[cl[0] - 0.5], (np.array(cl[1:]) + np.array(cl[:-1])) / 2, [cl[-1] + 0.5]]) if len(cl) > 1 else [cl[0] - .5, cl[0] + .5]
        ax.imshow(np.ma.array(disp, mask=dmask), cmap=lut, norm=BoundaryNorm(bounds, lut.N), extent=extent, interpolation="nearest")
        tot = counts.sum()

        def _extra(n):
            if not legend_stats:
                return ""
            if crs is not None and not geographic:
                return f"  {n * pixel_area / 1e4:,.0f} ha ({n / tot * 100:.1f}%)"
            return f"  ({n / tot * 100:.1f}%)"
        idx = list(range(len(cl)))
        if kind == "Change / transition":  # one "No change" entry, then conversions by area
            pers = [i for i in idx if cl[i] // 10 == cl[i] % 10]
            if pers:
                legend_items.append(Patch(fc="#E6E6E6", ec="#333", lw=0.4, label="No change (persistence)" + _extra(counts[pers].sum())))
            idx = sorted([i for i in idx if i not in pers], key=lambda k: -counts[k])
            shown = idx[:max_legend]
        else:
            shown = sorted(np.argsort(-counts)[:max_legend].tolist(), key=lambda k: cl[k])
        for i in shown:
            name = (labels or {}).get(str(int(cl[i]))) or f"Class {int(cl[i])}"
            legend_items.append(Patch(fc=cols[cl[i]], ec="#333", lw=0.4, label=f"{name}{_extra(counts[i])}"))
        if len(idx) > max_legend:
            legend_items.append(Patch(fc="white", ec="white", label=f"… {len(idx) - max_legend} smaller classes not listed"))
    else:  # continuous
        cm = cmap or CONTINUOUS.get(index_name or "", "viridis")
        v = arr[~full_mask].astype("float64")
        lo = vmin if vmin is not None else (float(np.percentile(v, 2)) if v.size else 0)
        hi = vmax if vmax is not None else (float(np.percentile(v, 98)) if v.size else 1)
        if kind == "Spectral index" and vmin is None and vmax is None:
            lo, hi = max(-1.0, lo), min(1.0, hi)
        im = ax.imshow(np.ma.array(disp, mask=dmask), cmap=cm, vmin=lo, vmax=hi, extent=extent, interpolation="nearest")
        cax = fig.add_axes([0.74, 0.40, 0.03, 0.40])
        cbar = fig.colorbar(im, cax=cax, extend="both")
        cbar.ax.tick_params(labelsize=8)
        cbar.set_label(index_name or layer_name or "Value", fontsize=9)
        if v.size:
            lax.text(0.32, 0.30, f"min  {v.min():.3f}\nmean {v.mean():.3f}\nmax  {v.max():.3f}\nstd  {v.std():.3f}",
                     transform=lax.transAxes, fontsize=8, family="monospace", va="top")

    lax.text(0.0, 1.0, "Legend", fontsize=12, fontweight="bold", va="top", transform=lax.transAxes)
    if legend_items:
        lax.legend(handles=legend_items, loc="upper left", bbox_to_anchor=(0, 0.93), frameon=False, fontsize=8,
                   handlelength=1.6, handleheight=1.1, labelspacing=0.55)
    if full_mask.any():
        lax.text(0.0, 0.0, "□ NoData / outside study area", fontsize=7.5, color="#666", transform=lax.transAxes)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_facecolor("white")
    for s in ax.spines.values():
        s.set_linewidth(1.2)
    if show_grid:
        ax.grid(True, color="#000", alpha=0.25, lw=0.5, ls="--")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _fmt_coord(v, geographic, "x")))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _fmt_coord(v, geographic, "y")))
        ax.tick_params(labelsize=7, direction="in", top=True, right=True)
        plt.setp(ax.get_yticklabels(), rotation=90, va="center")
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(5))
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(5))
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    if show_scale:
        draw_scalebar(ax, extent, crs)
    if show_north:
        draw_north_arrow(ax, extent)

    crs_txt = (crs.to_string() if crs is not None else "unknown")
    if crs is not None and crs.to_epsg():
        crs_txt = f"EPSG:{crs.to_epsg()}"
    px = f"{abs(transform.a):g} × {abs(transform.e):g} {'°' if geographic else 'm'}"
    meta = [("Coordinate system", crs_txt), ("Pixel size", px), ("Size", f"{w:,} × {h:,} px"),
            ("Layer", layer_name or "-"), ("Data source", source or "User-supplied GeoTIFF"),
            ("Author", author or "-"), ("Date", datetime.date.today().isoformat())]
    iax.add_patch(Rectangle((0.002, 0.004), 0.996, 0.992, transform=iax.transAxes, fc="#F7F7F7", ec="#999", lw=0.6, clip_on=False))
    for i, (k, val) in enumerate(meta):
        yy = 0.9 - i * 0.125
        iax.text(0.04, yy, k, fontsize=7.5, fontweight="bold", transform=iax.transAxes, va="center")
        iax.text(0.42, yy, str(val)[:38], fontsize=7.5, transform=iax.transAxes, va="center")
    note = "Grid north; scale bar approximate at map centre." if geographic else "Grid north (projected CRS)."
    if step > 1:
        note += f" Display decimated 1:{step}; statistics at full resolution."
    fig.text(0.05, 0.035, note + (f"  ·  Produced with LULC Agent v{version}" if version else ""), fontsize=7, color="#666")
    fig.add_artist(Rectangle((0.012, 0.015), 0.976, 0.97, transform=fig.transFigure, fill=False, ec="#333", lw=1.4))
    return fig


def fig_bytes(fig, fmt="png", dpi=200):
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ---------------- fast live-canvas frame ----------------
def preview_frame(arr, mask, done_rows, *, kind, cols=None, cmap="viridis", vmin=0, vmax=1, max_px=700):
    """RGB uint8 frame for the live canvas: processed rows in colour, pending rows dark with a scan line."""
    disp, dmask, s = downsample(arr, mask, max_px)
    hh, ww = dmask.shape
    out = np.full((hh, ww, 3), 28, "uint8")
    if kind == "RGB composite":
        rgb = np.dstack([stretch(disp[i], dmask) for i in range(3)])
        img = (rgb * 255).astype("uint8")
    elif cols is not None:
        img = np.zeros((hh, ww, 3), "uint8")
        for c, hexc in cols.items():
            img[disp == c] = [int(hexc[i:i + 2], 16) for i in (1, 3, 5)]
    else:
        cm = plt.get_cmap(cmap)
        img = (cm(np.clip((disp.astype("float32") - vmin) / ((vmax - vmin) or 1), 0, 1))[..., :3] * 255).astype("uint8")
    r = min(hh, int(math.ceil(done_rows / s)))
    out[:r] = img[:r]
    out[:r][dmask[:r]] = 245
    if r < hh:
        out[max(0, r - 1):r + 2] = [0, 229, 255]
    return out
