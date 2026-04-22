import sys

from PySide6.QtWidgets import QApplication

from .app import build_main_window


def create_application() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setStyle("Fusion")
    return app


def main() -> int:
    app = create_application()
    window = build_main_window()
    window.show()
    return app.exec()
