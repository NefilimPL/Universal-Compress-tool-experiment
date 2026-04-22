from PySide6.QtWidgets import QApplication

from universal_compress.app import build_main_window
from universal_compress.main import create_application
from universal_compress import main as main_module


def test_create_application_and_main_window(qtbot):
    app = create_application()
    window = build_main_window()
    qtbot.addWidget(window)

    assert isinstance(app, QApplication)
    assert window.windowTitle() == "Universal Compress V2"
    assert window.acceptDrops() is True


def test_main_shows_window_and_runs_event_loop(monkeypatch):
    shown = []

    class DummyApplication:
        def exec(self):
            shown.append("exec")
            return 17

    class DummyWindow:
        def show(self):
            shown.append("show")

    dummy_app = DummyApplication()
    dummy_window = DummyWindow()

    monkeypatch.setattr(main_module, "create_application", lambda: dummy_app)
    monkeypatch.setattr(main_module, "build_main_window", lambda: dummy_window)

    assert main_module.main() == 17
    assert shown == ["show", "exec"]
