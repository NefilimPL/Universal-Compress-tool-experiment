from __future__ import annotations

from .algorithms import AVAILABLE_ALGOS
from .error_logging import install_global_exception_handlers
from .gui import App


def main():
    install_global_exception_handlers()
    if not AVAILABLE_ALGOS:
        raise RuntimeError("Ten interpreter Pythona nie ma dost?pnego ?adnego modu?u kompresji z zestawu: zlib/gzip/bz2/lzma.")
    app = App()
    app.mainloop()
