from __future__ import annotations

try:
    import zlib
except Exception:
    zlib = None

try:
    import gzip
except Exception:
    gzip = None

try:
    import bz2
except Exception:
    bz2 = None

try:
    import lzma
except Exception:
    lzma = None


ALGO_META = {
    "zlib": {"label": "ZLIB", "min": 0, "max": 9, "default": 6, "available": zlib is not None},
    "gzip": {"label": "GZIP", "min": 0, "max": 9, "default": 6, "available": gzip is not None},
    "bz2": {"label": "BZ2", "min": 1, "max": 9, "default": 9, "available": bz2 is not None},
    "lzma": {"label": "LZMA/XZ", "min": 0, "max": 9, "default": 6, "available": lzma is not None},
}
AVAILABLE_ALGOS = [name for name, meta in ALGO_META.items() if meta["available"]]


def clamp_level(algo: str, level: int) -> int:
    meta = ALGO_META[algo]
    return max(meta["min"], min(meta["max"], int(level)))


def ensure_algorithm_available(algo: str) -> None:
    meta = ALGO_META.get(algo)
    if meta is None:
        raise ValueError(f"Nieobs?ugiwany algorytm: {algo}")
    if not meta["available"]:
        raise RuntimeError(f"Modu? dla algorytmu {meta['label']} nie jest dost?pny w tym Pythonie.")


class ZlibWriteAdapter:
    def __init__(self, raw_f, level: int):
        if zlib is None:
            raise RuntimeError("Modu? zlib nie jest dost?pny w tym Pythonie.")
        self.raw_f = raw_f
        self._comp = zlib.compressobj(level)
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("Strumie? zlib jest zamkni?ty.")
        if data:
            out = self._comp.compress(data)
            if out:
                self.raw_f.write(out)
        return len(data)

    def close(self) -> None:
        if self._closed:
            return
        tail = self._comp.flush(zlib.Z_FINISH)
        if tail:
            self.raw_f.write(tail)
        self._closed = True

    def flush(self) -> None:
        if self._closed:
            return
        out = self._comp.flush(zlib.Z_SYNC_FLUSH)
        if out:
            self.raw_f.write(out)
        self.raw_f.flush()


def open_compressed_writer(algo: str, raw_f, level: int):
    level = clamp_level(algo, level)
    ensure_algorithm_available(algo)

    if algo == "gzip":
        return gzip.GzipFile(fileobj=raw_f, mode="wb", compresslevel=level, mtime=0)
    if algo == "bz2":
        return bz2.BZ2File(raw_f, mode="wb", compresslevel=level)
    if algo == "lzma":
        return lzma.LZMAFile(raw_f, mode="wb", preset=level, format=lzma.FORMAT_XZ)
    if algo == "zlib":
        return ZlibWriteAdapter(raw_f, level=level)

    raise ValueError(f"Nieobs?ugiwany algorytm: {algo}")
