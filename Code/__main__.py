from __future__ import annotations

from .runtime_bootstrap import ensure_runtime_dependencies, show_bootstrap_error


def run() -> None:
    try:
        ensure_runtime_dependencies()
    except RuntimeError as exc:
        show_bootstrap_error(str(exc))
        raise SystemExit(1) from exc

    from .pylossless.main import main

    main()


if __name__ == "__main__":
    run()
