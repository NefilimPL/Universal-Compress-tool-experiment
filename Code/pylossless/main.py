from __future__ import annotations

from .algorithms import AVAILABLE_ALGOS
from .gui import App


def main():
    if not AVAILABLE_ALGOS:
        raise RuntimeError("Ten interpreter Pythona nie ma dost?pnego ?adnego modu?u kompresji z zestawu: zlib/gzip/bz2/lzma.")
    app = App()
    app.mainloop()
