from __future__ import annotations

from .runtime_bootstrap import bootstrap_and_run


def run() -> None:
    def start_gui() -> None:
        from .pylossless.main import main as gui_main

        gui_main()

    bootstrap_and_run(start_gui)


if __name__ == "__main__":
    run()
