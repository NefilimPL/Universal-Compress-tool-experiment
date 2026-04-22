from __future__ import annotations

from .runtime_bootstrap import bootstrap_and_run, default_runtime_requirements_path


def run() -> None:
    def start_gui() -> None:
        from .universal_compress.main import main as app_main

        app_main()

    bootstrap_and_run(start_gui, requirements_path=default_runtime_requirements_path())


if __name__ == "__main__":
    run()
