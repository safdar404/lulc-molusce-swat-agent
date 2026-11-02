"""In-memory raster store: uploaded GeoTIFFs are read once and never written to disk."""
from dataclasses import dataclass
import numpy as np
from rasterio.io import MemoryFile


@dataclass
class Raster:
    name: str
    data: np.ndarray
    mask: np.ndarray      # True where NoData / invalid
    nodata: object
    transform: object
    crs: object
    profile: dict
    bands: object = None        # (count, rows, cols) array for multi-band files, else None
    descriptions: tuple = ()


class Store:
    def __init__(self):
        self.rasters, self.outputs = {}, {}

    def add(self, name, raw, register=True):
        with MemoryFile(raw) as mf, mf.open() as src:
            stack = src.read()
            a = stack[0]
            nd = src.nodata
            m = np.zeros(a.shape, bool) if nd is None else (stack == nd).any(0)
            if a.dtype.kind == "f":
                m = m | ~np.isfinite(stack).all(0)
            r = Raster(name, a, m, nd, src.transform, src.crs, src.profile,
                       stack if stack.shape[0] > 1 else None, tuple(d or "" for d in src.descriptions))
        if register:
            self.rasters[name] = r
        return r

    def get(self, name):
        if "#" in name and name not in self.rasters and name not in self.outputs:  # one band of a multi-band file: "stack.tif#4"
            base, _, b = name.rpartition("#")
            src = self.get(base)
            if src.bands is None or not b.isdigit() or not 1 <= int(b) <= src.bands.shape[0]:
                raise ValueError(f"{name}: band not found (file has {1 if src.bands is None else src.bands.shape[0]} band(s)).")
            return Raster(name, src.bands[int(b) - 1], src.mask, src.nodata, src.transform, src.crs, src.profile)
        if name not in self.rasters and name in self.outputs:  # generated outputs can be re-used as inputs (e.g. mapped)
            cache = self.__dict__.setdefault("_out_cache", {})
            if name not in cache or cache[name][0] is not self.outputs[name]:
                cache[name] = (self.outputs[name], self.add(name, self.outputs[name], register=False))
            return cache[name][1]
        if name not in self.rasters:
            raise ValueError(f"Raster not loaded: {name}. Loaded: {list(self.rasters)}")
        return self.rasters[name]

    def names(self):
        out = []
        for n, r in self.rasters.items():
            out.append(n)
            if r.bands is not None:  # expose each band of a multi-band stack as "name#k"
                out += [f"{n}#{i}" for i in range(1, r.bands.shape[0] + 1)]
        return out

    def band_count(self, name):
        r = self.get(name)
        return 1 if r.bands is None else r.bands.shape[0]


def to_geotiff_bytes(profile, arr, dtype, nodata):
    p = {k: v for k, v in profile.items() if k not in ("blockxsize", "blockysize", "tiled", "interleave")}
    p.update(driver="GTiff", count=1, dtype=dtype, nodata=nodata, compress="lzw")
    with MemoryFile() as mf:
        with mf.open(**p) as dst:
            dst.write(arr.astype(dtype), 1)
        return mf.read()
