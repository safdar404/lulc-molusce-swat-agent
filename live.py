"""Block-wise ("live") raster processing for the real-time map canvas.

Each job processes the raster in horizontal strips. After every strip the caller gets the running statistics and can
redraw the canvas, so the user watches the result being built. All arithmetic is identical to rasterops.py and runs at
full resolution; only the canvas preview is decimated.
"""
from dataclasses import dataclass, field

import numpy as np

import cartography
from store import to_geotiff_bytes

OPERATIONS = ["Classified LULC map", "Spectral index (NDVI / NDWI / NDBI)", "LULC change (from → to)",
              "Hindcast disagreement (observed vs simulated)", "Satellite RGB composite", "Continuous raster (DEM, band, index)"]


@dataclass
class LiveJob:
    op: str
    kind: str
    arr: np.ndarray
    mask: np.ndarray
    transform: object
    crs: object
    profile: dict
    step: object                       # fn(r0, r1) -> None, fills arr/mask rows r0:r1
    out_name: str = ""
    out_dtype: str = "float32"
    out_nodata: object = -9999
    index_name: str = None
    labels: dict = field(default_factory=dict)
    pixel_area: float = 0.0
    rows_done: int = 0

    @property
    def rows(self):
        return self.mask.shape[0]

    def stats(self):
        r = self.rows_done
        ok = ~self.mask[:r]
        if self.arr.ndim == 3:
            n = int(ok.sum())
            return {"valid pixels": n, **{f"mean {c}": float(self.arr[i, :r][ok].mean()) if n else None for i, c in enumerate("RGB")}}
        v = self.arr[:r][ok]
        out = {"rows": f"{r}/{self.rows}", "valid pixels": int(v.size)}
        if not v.size:
            return out
        if self.kind in ("LULC (classified)", "Change / transition", "Disagreement"):
            cls, cnt = np.unique(v, return_counts=True)
            out["classes"] = {int(c): (round(float(n * self.pixel_area / 1e4), 1) if self.pixel_area else int(n)) for c, n in zip(cls, cnt)}
            out["unit"] = "ha" if self.pixel_area else "pixels"
            if self.kind == "Disagreement":
                out["disagreement %"] = round(float((v == 1).mean() * 100), 2)
            if self.kind == "Change / transition":
                out["changed %"] = round(float(((v // 10) != (v % 10)).mean() * 100), 2)
        else:
            out.update(min=round(float(v.min()), 4), mean=round(float(v.mean()), 4), max=round(float(v.max()), 4))
        return out

    def geotiff(self):
        if self.arr.ndim == 3:
            return None
        res = np.where(self.mask, self.out_nodata, self.arr).astype(self.out_dtype)
        return to_geotiff_bytes(self.profile, res, self.out_dtype, self.out_nodata)


def _pair(store, a, b):
    x, y = store.get(a), store.get(b)
    if x.data.shape != y.data.shape:
        raise ValueError(f"{a} and {b} differ in size. Run the geometry check and align them first.")
    return x, y


def _area(r):
    return abs(r.transform.a * r.transform.e) if (r.crs is not None and r.crs.is_projected) else 0.0


def build(store, op, layers, *, index="NDVI", labels=None, out_name=""):
    """Create a LiveJob. `layers` is the list of raster names the operation needs."""
    labels = labels or {}
    if op == "Classified LULC map":
        r = store.get(layers[0])
        arr, mask = np.zeros(r.data.shape, r.data.dtype), np.ones(r.data.shape, bool)

        def step(a, b):
            arr[a:b], mask[a:b] = r.data[a:b], r.mask[a:b]
        return LiveJob(op, "LULC (classified)", arr, mask, r.transform, r.crs, r.profile, step, out_name or f"map_{layers[0]}",
                       str(r.data.dtype), r.nodata if r.nodata is not None else 0, labels=labels, pixel_area=_area(r))

    if op.startswith("Spectral index"):
        x, y = _pair(store, layers[0], layers[1])
        arr, mask = np.zeros(x.data.shape, "float32"), np.ones(x.data.shape, bool)

        def step(a, b):
            p, q = x.data[a:b].astype("float32"), y.data[a:b].astype("float32")
            den = p + q
            bad = x.mask[a:b] | y.mask[a:b] | (den == 0)
            arr[a:b] = np.where(bad, 0, (p - q) / np.where(den == 0, 1, den))
            mask[a:b] = bad
        return LiveJob(op, "Spectral index", arr, mask, x.transform, x.crs, x.profile, step, out_name or f"{index}.tif", index_name=index)

    if op.startswith("LULC change"):
        x, y = _pair(store, layers[0], layers[1])
        ok = ~(x.mask | y.mask)
        if ok.any() and max(int(x.data[ok].max()), int(y.data[ok].max())) >= 10:
            raise ValueError("Class codes must be 0–9 for the old×10+new encoding.")
        arr, mask = np.zeros(x.data.shape, "int32"), np.ones(x.data.shape, bool)

        def step(a, b):
            arr[a:b] = x.data[a:b].astype("int32") * 10 + y.data[a:b].astype("int32")
            mask[a:b] = x.mask[a:b] | y.mask[a:b]
        lab = dict(labels)
        lab["_base"] = labels
        if labels:
            for o in labels:
                for n in labels:
                    if o.isdigit() and n.isdigit():
                        lab[str(int(o) * 10 + int(n))] = f"No change ({labels[o]})" if o == n else f"{labels[o]} → {labels[n]}"
        return LiveJob(op, "Change / transition", arr, mask, x.transform, x.crs, x.profile, step, out_name or "transition.tif",
                       "int32", -9999, labels=lab, pixel_area=_area(x))

    if op.startswith("Hindcast"):
        x, y = _pair(store, layers[0], layers[1])
        arr, mask = np.zeros(x.data.shape, "uint8"), np.ones(x.data.shape, bool)

        def step(a, b):
            arr[a:b] = (x.data[a:b] != y.data[a:b]).astype("uint8")
            mask[a:b] = x.mask[a:b] | y.mask[a:b]
        return LiveJob(op, "Disagreement", arr, mask, x.transform, x.crs, x.profile, step, out_name or "disagreement.tif",
                       "uint8", 255, pixel_area=_area(x))

    if op.startswith("Satellite RGB"):
        rr = [store.get(n) for n in layers[:3]]
        if len({r.data.shape for r in rr}) != 1:
            raise ValueError("The three bands differ in size; align them first.")
        shp = rr[0].data.shape
        arr, mask = np.zeros((3,) + shp, "float32"), np.ones(shp, bool)

        def step(a, b):
            for i, r in enumerate(rr):
                arr[i, a:b] = r.data[a:b]
            mask[a:b] = rr[0].mask[a:b] | rr[1].mask[a:b] | rr[2].mask[a:b]
        return LiveJob(op, "RGB composite", arr, mask, rr[0].transform, rr[0].crs, rr[0].profile, step,
                       labels={"r": layers[0], "g": layers[1], "b": layers[2]})

    r = store.get(layers[0])
    arr, mask = np.zeros(r.data.shape, "float32"), np.ones(r.data.shape, bool)

    def step(a, b):
        arr[a:b], mask[a:b] = r.data[a:b], r.mask[a:b]
    return LiveJob(op, "Continuous", arr, mask, r.transform, r.crs, r.profile, step, out_name or f"map_{layers[0]}")


def run(job, n_blocks=16):
    """Generator: processes the job strip by strip, yielding after each strip."""
    edges = np.linspace(0, job.rows, max(1, min(n_blocks, job.rows)) + 1).astype(int)
    for a, b in zip(edges[:-1], edges[1:]):
        job.step(a, b)
        job.rows_done = int(b)
        yield job


def frame_style(job, sources):
    """Colours / colour ramp for the live canvas, fixed from the full inputs up front so colours don't jump while streaming."""
    if job.kind in ("LULC (classified)", "Change / transition", "Disagreement"):
        if job.kind == "Disagreement":
            classes = [0, 1]
        else:
            ok = ~sources[0].mask
            if job.kind == "Change / transition":
                ok &= ~sources[1].mask
                classes = np.unique(sources[0].data[ok].astype("int32") * 10 + sources[1].data[ok].astype("int32")).tolist()
            else:
                classes = np.unique(sources[0].data[ok]).tolist()
        return dict(cols=cartography.categorical_colours(job.kind, classes, job.labels)[0])
    if job.kind == "Spectral index":
        return dict(cmap=cartography.CONTINUOUS.get(job.index_name, "RdYlGn"), vmin=-1, vmax=1)
    if job.kind == "Continuous":
        v = sources[0].data[~sources[0].mask]
        lo, hi = (np.percentile(v, [2, 98]) if v.size else (0, 1))
        return dict(cmap="terrain", vmin=float(lo), vmax=float(hi))
    return {}
