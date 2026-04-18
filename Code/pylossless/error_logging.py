from __future__ import annotations

import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Iterable

from .constants import APP_NAME, APP_VERSION
from .paths import LOGS_DIR
from .utils import ensure_dir

_HOOKS_INSTALLED = False
_PREVIOUS_SYS_EXCEPHOOK = sys.excepthook
_PREVIOUS_THREADING_EXCEPHOOK = getattr(threading, "excepthook", None)


def _build_log_path() -> Path:
    ensure_dir(LOGS_DIR)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"{time.time_ns() % 1_000_000_000:09d}"
    return LOGS_DIR / f"error_{stamp}_{suffix}.txt"


def _normalized_extra_lines(extra_lines: Iterable[str] | None) -> list[str]:
    if extra_lines is None:
        return []
    return [str(line) for line in extra_lines]


def build_error_report(
    *,
    title: str,
    message: str,
    traceback_text: str = "",
    context: str | None = None,
    extra_lines: Iterable[str] | None = None,
) -> str:
    lines = [
        title,
        "=" * len(title),
        "",
        f"Aplikacja: {APP_NAME} {APP_VERSION}",
        f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"PID: {os.getpid()}",
        f"Python: {sys.version.split()[0]}",
        f"System: {platform.platform()}",
        f"Katalog roboczy: {Path.cwd()}",
    ]

    if context:
        lines.extend(["", f"Kontekst: {context}"])

    lines.extend(["", "Wiadomo??:", message])

    extra = _normalized_extra_lines(extra_lines)
    if extra:
        lines.extend(["", "Dodatkowe informacje:"])
        lines.extend(extra)

    if traceback_text:
        lines.extend(["", "Traceback:", traceback_text.rstrip()])

    lines.append("")
    return "\n".join(lines)


def write_error_report(
    *,
    title: str,
    message: str,
    traceback_text: str = "",
    context: str | None = None,
    extra_lines: Iterable[str] | None = None,
) -> Path:
    path = _build_log_path()
    report = build_error_report(
        title=title,
        message=message,
        traceback_text=traceback_text,
        context=context,
        extra_lines=extra_lines,
    )
    path.write_text(report, encoding="utf-8")
    return path


def write_exception_report(
    exc_type,
    exc_value,
    exc_traceback,
    *,
    title: str = "Nieobs?u?ony wyj?tek",
    context: str | None = None,
    extra_lines: Iterable[str] | None = None,
) -> Path:
    traceback_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    return write_error_report(
        title=title,
        message=f"{exc_type.__name__}: {exc_value}",
        traceback_text=traceback_text,
        context=context,
        extra_lines=extra_lines,
    )


def _safe_write_exception_report(exc_type, exc_value, exc_traceback, *, context: str) -> Path | None:
    try:
        return write_exception_report(exc_type, exc_value, exc_traceback, context=context)
    except Exception:
        print(f"[{APP_NAME}] Nie uda?o si? zapisa? raportu b??du.", file=sys.stderr)
        traceback.print_exc()
        return None


def install_global_exception_handlers() -> None:
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True

    def handle_sys_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return _PREVIOUS_SYS_EXCEPHOOK(exc_type, exc_value, exc_traceback)

        log_path = _safe_write_exception_report(
            exc_type,
            exc_value,
            exc_traceback,
            context="Globalny wyj?tek w g??wnym w?tku aplikacji.",
        )
        if log_path is not None:
            print(f"[{APP_NAME}] Raport b??du zapisano do: {log_path}", file=sys.stderr)
        _PREVIOUS_SYS_EXCEPHOOK(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_sys_exception

    if _PREVIOUS_THREADING_EXCEPHOOK is not None:

        def handle_thread_exception(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                return _PREVIOUS_THREADING_EXCEPHOOK(args)

            thread_name = args.thread.name if args.thread is not None else "nieznany w?tek"
            log_path = _safe_write_exception_report(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                context=f"Globalny wyj?tek w w?tku: {thread_name}.",
            )
            if log_path is not None:
                print(f"[{APP_NAME}] Raport b??du zapisano do: {log_path}", file=sys.stderr)
            _PREVIOUS_THREADING_EXCEPHOOK(args)

        threading.excepthook = handle_thread_exception
