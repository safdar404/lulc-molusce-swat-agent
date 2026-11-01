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


class Store:
    def __init__(self):
        self.rasters, self.outputs = {}, {}

    def add(self, name, raw):
        with MemoryFile(raw) as mf, mf.open() as src:
            a = src.read(1)
            nd = src.nodata
            m = np.zeros(a.shape, bool) if nd is None else (a == nd)
            if a.dtype.kind == "f":
                m = m | ~np.isfinite(a)
            self.rasters[name] = Raster(name, a, m, nd, src.transform, src.crs, src.profile)
        return self.rasters[name]

    def get(self, name):
        if name not in self.rasters:
            raise ValueError(f"Raster not loaded: {name}. Loaded: {list(self.rasters)}")
        return self.rasters[name]

    def names(self):
        return list(self.rasters)


def to_geotiff_bytes(profile, arr, dtype, nodata):
    p = {k: v for k, v in profile.items() if k not in ("blockxsize", "blockysize", "tiled", "interleave")}
    p.update(driver="GTiff", count=1, dtype=dtype, nodata=nodata, compress="lzw")
    with MemoryFile() as mf:
        with mf.open(**p) as dst:
            dst.write(arr.astype(dtype), 1)
        return mf.read()
