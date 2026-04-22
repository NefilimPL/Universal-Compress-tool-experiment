import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from universal_compress.ui.main_window import MainWindow
from universal_compress.models import CancelledError


def test_main_window_adds_source_paths_and_updates_cost(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.add_source_paths([source])

    assert window.source_list.count() == 1
    assert "niski" in window.inspector.cost_label.text().lower()


def test_main_window_exposes_primary_actions(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.add_files_button.text() == "Dodaj pliki"
    assert window.add_folder_button.text() == "Dodaj folder"
    assert window.clear_button.text() == "Wyczysc"
    assert window.stop_button.text() == "Zatrzymaj"
    assert window.stop_button.isEnabled() is False
    assert window.source_list.acceptDrops() is True


def test_main_window_styles_explicitly_theme_problematic_native_controls(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    stylesheet = window.styleSheet()

    assert "QMenuBar {" in stylesheet
    assert "QMenu {" in stylesheet
    assert "QFrame#sectionCard, QFrame#subCard, QFrame#dropzoneCard {" in stylesheet
    assert "QScrollBar:horizontal {" in stylesheet
    assert "QComboBox::drop-down {" in stylesheet
    assert "QTabWidget::pane {" in stylesheet
    assert "QPushButton#primaryAction {" in stylesheet

    hero_block = stylesheet.split("QLabel#heroTitle {", 1)[1].split("}", 1)[0]
    panel_block = stylesheet.split("QLabel#panelTitle, QLabel#cardTitle {", 1)[1].split("}", 1)[0]

    assert "color:" in hero_block
    assert "color:" in panel_block


def test_main_window_uses_task_first_workspace_sections(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.main_columns_layout.stretch(0) == 7
    assert window.main_columns_layout.stretch(1) == 3
    assert window.sidebar_widget.minimumWidth() >= 340
    assert window.queue_tabs.count() == 2
    assert window.queue_tabs.tabText(0) == "Kolejka"
    assert window.queue_tabs.tabText(1) == "Aktywnosc"


def test_main_window_surfaces_dropzone_and_guided_setting_labels(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.dropzone_title.text() == "Upusc pliki lub foldery"
    assert "Przeciagnij" in window.dropzone_hint.text()
    assert window.dropzone_card.acceptDrops() is True
    assert window.inspector.mode_label.text() == "Format archiwum"
    assert window.inspector.profile_label.text() == "Tryb kompresji"
    assert window.inspector.protection_label.text() == "Zabezpieczenie"


def test_task_history_wraps_without_horizontal_scrollbar(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    history_list = window.task_history.history_list

    assert history_list.wordWrap() is True
    assert history_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_main_window_default_layout_gives_more_height_to_workspace_than_queue(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert window.workspace_card.height() > window.queue_card.height()


def test_main_window_default_layout_does_not_clip_dropzone_or_sidebar(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert window.dropzone_card.height() >= window.dropzone_card.minimumSizeHint().height()
    assert window.sidebar_widget.widgetResizable() is True
    assert window.inspector.height() >= window.inspector.minimumSizeHint().height()


def test_queue_tab_uses_compact_content_without_nested_headers(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert window.task_history.layout().count() == 1
    assert window.task_history.history_list.height() >= 80


def test_inspector_fields_follow_vertical_order_without_overlap(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert window.inspector.mode_label.geometry().bottom() < window.inspector.mode_combo.geometry().top()
    assert window.inspector.mode_combo.geometry().bottom() < window.inspector.profile_label.geometry().top()
    assert window.inspector.profile_label.geometry().bottom() < window.inspector.profile_combo.geometry().top()
    assert window.inspector.profile_combo.geometry().bottom() < window.inspector.protection_label.geometry().top()
    assert window.inspector.protection_label.geometry().bottom() < window.inspector.protection_combo.geometry().top()


def test_inspector_uses_clear_polish_summary_copy(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert "Szacowany koszt" in window.inspector.cost_label.text()
    assert "Obciazenie sprzetu" in window.inspector.load_label.text()
    assert "domyslnym" in window.inspector.explainer_label.text().lower()


def test_mode_selection_updates_primary_action_and_format_hint(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert "UCA" in window.start_button.text()
    assert ".uca" in window.inspector.format_hint_label.text().lower()

    window.inspector.mode_combo.setCurrentText("ZIP (zgodnosc)")

    assert "ZIP" in window.start_button.text()
    assert ".zip" in window.inspector.format_hint_label.text().lower()

    window.inspector.mode_combo.setCurrentText("Media Studio")

    assert "Media Studio" in window.start_button.text()
    assert "media" in window.inspector.format_hint_label.text().lower()


def test_start_button_creates_archive_and_reports_success(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    output = tmp_path / "wynik.uca"

    class FakeArchiveService:
        def __init__(self) -> None:
            self.calls = []

        def create_archive(self, sources, plan, progress_callback=None):
            self.calls.append((sources, plan))
            if progress_callback is not None:
                progress_callback(1, len(sources), sources[0])
            plan.output_path.write_text("archive", encoding="utf-8")
            return plan.output_path

    archive_service = FakeArchiveService()
    window = MainWindow(
        archive_service=archive_service,
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: output.exists(), timeout=2000)
    qtbot.waitUntil(lambda: len(archive_service.calls) == 1, timeout=2000)
    qtbot.waitUntil(lambda: "Utworzono archiwum" in window.statusBar().currentMessage(), timeout=2000)
    assert output.exists() is True
    assert len(archive_service.calls) == 1
    assert "Utworzono archiwum" in window.statusBar().currentMessage()


def test_start_button_updates_visible_progress_and_last_output(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    output = tmp_path / "wynik.uca"

    class FakeArchiveService:
        def create_archive(self, sources, plan, progress_callback=None):
            if progress_callback is not None:
                progress_callback(1, len(sources), sources[0])
            plan.output_path.write_text("archive", encoding="utf-8")
            return plan.output_path

    window = MainWindow(
        archive_service=FakeArchiveService(),
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: output.exists(), timeout=2000)
    qtbot.waitUntil(lambda: window.inspector.progress_bar.value() == 100, timeout=2000)
    assert window.inspector.progress_bar.value() == 100
    assert "zakonczono" in window.inspector.job_status_label.text().lower()
    assert output.name in window.inspector.last_output_label.text()
    assert "demo.txt" in window.inspector.progress_detail_label.text()


def test_media_studio_cancellation_does_not_open_archive_save_dialog(qtbot, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_text("video", encoding="utf-8")
    save_dialog_calls = []

    class FakeArchiveService:
        def create_archive(self, sources, plan, progress_callback=None):
            raise AssertionError("Media Studio should not call archive creation")

    class FakeMediaService:
        def compress_sources(self, sources, output_dir_arg, profile_name, progress_callback=None, log_callback=None):
            raise AssertionError("Cancelled Media Studio should not reach media compression")

    window = MainWindow(
        archive_service=FakeArchiveService(),
        media_service=FakeMediaService(),
        choose_directory_dialog=lambda *args, **kwargs: "",
        save_file_dialog=lambda *args, **kwargs: save_dialog_calls.append((args, kwargs)),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])
    window.inspector.mode_combo.setCurrentText("Media Studio")

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    assert save_dialog_calls == []
    assert "anulowano" in window.inspector.job_status_label.text().lower()
    assert "folderu" in window.inspector.progress_detail_label.text().lower()


def test_start_button_requires_sources_before_creating_archive(qtbot, tmp_path):
    output = tmp_path / "wynik.uca"

    class FakeArchiveService:
        def create_archive(self, sources, plan):
            raise AssertionError("create_archive should not be called without sources")

    window = MainWindow(
        archive_service=FakeArchiveService(),
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    assert "Dodaj przynajmniej jedno zrodlo" in window.statusBar().currentMessage()


def test_start_button_runs_archive_creation_off_main_thread(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    output = tmp_path / "wynik.uca"
    started = threading.Event()
    release = threading.Event()

    class FakeArchiveService:
        def __init__(self) -> None:
            self.thread_id = None

        def create_archive(self, sources, plan, progress_callback=None):
            self.thread_id = threading.get_ident()
            started.set()
            if progress_callback is not None:
                progress_callback(1, len(sources), sources[0])
            release.wait(timeout=0.2)
            plan.output_path.write_text("archive", encoding="utf-8")
            return plan.output_path

    archive_service = FakeArchiveService()
    window = MainWindow(
        archive_service=archive_service,
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    assert started.wait(0.5) is True
    assert archive_service.thread_id != threading.get_ident()
    assert window.start_button.isEnabled() is False

    release.set()
    qtbot.waitUntil(lambda: output.exists(), timeout=2000)
    qtbot.waitUntil(lambda: window.start_button.isEnabled() is True, timeout=2000)


def test_media_studio_uses_media_service_and_output_directory(qtbot, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_text("video", encoding="utf-8")
    output_dir = tmp_path / "media_out"
    saved_outputs = []

    class FakeArchiveService:
        def create_archive(self, sources, plan, progress_callback=None):
            raise AssertionError("Archive service should not be used in Media Studio mode")

    class FakeMediaService:
        def __init__(self) -> None:
            self.calls = []

        def compress_sources(self, sources, output_dir_arg, profile_name, progress_callback=None, log_callback=None):
            self.calls.append((sources, output_dir_arg, profile_name))
            output_dir_arg.mkdir(parents=True, exist_ok=True)
            if progress_callback is not None:
                progress_callback(1, 1, f"Media 1/1: {sources[0].name}")
            output_path = output_dir_arg / "clip_compressed.mp4"
            output_path.write_text("done", encoding="utf-8")
            saved_outputs.append(output_path)
            return saved_outputs

    media_service = FakeMediaService()
    window = MainWindow(
        archive_service=FakeArchiveService(),
        media_service=media_service,
        choose_directory_dialog=lambda *args, **kwargs: str(output_dir),
        save_file_dialog=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("save file dialog should not open")),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])
    window.inspector.mode_combo.setCurrentText("Media Studio")

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: bool(saved_outputs) and saved_outputs[0].exists(), timeout=2000)
    qtbot.waitUntil(lambda: window.inspector.progress_bar.value() == 100, timeout=2000)

    assert len(media_service.calls) == 1
    assert media_service.calls[0][1] == output_dir
    assert media_service.calls[0][2] == window.inspector.profile_combo.currentText()
    assert window.inspector.progress_bar.value() == 100
    assert "zakonczono" in window.inspector.job_status_label.text().lower()
    assert "clip_compressed.mp4" in window.inspector.last_output_label.text()


def test_stop_button_cancels_running_archive_job(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    output = tmp_path / "wynik.uca"
    started = threading.Event()
    cancel_seen = threading.Event()

    class FakeArchiveService:
        def create_archive(self, sources, plan, progress_callback=None, cancel_event=None):
            assert cancel_event is not None
            started.set()
            while not cancel_event.is_set():
                QTest.qWait(10)
            cancel_seen.set()
            raise CancelledError("Operacja zostala anulowana.")

    window = MainWindow(
        archive_service=FakeArchiveService(),
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)
    window.add_source_paths([source])

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    assert started.wait(0.5) is True
    qtbot.waitUntil(lambda: window.stop_button.isEnabled() is True, timeout=1000)

    QTest.mouseClick(window.stop_button, Qt.LeftButton)

    assert cancel_seen.wait(0.5) is True
    qtbot.waitUntil(lambda: "anulowano" in window.inspector.job_status_label.text().lower(), timeout=2000)
    qtbot.waitUntil(lambda: window.start_button.isEnabled() is True, timeout=2000)
    assert "anulowano" in window.statusBar().currentMessage().lower()


def test_closing_window_cancels_running_job_before_exit(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    output = tmp_path / "wynik.uca"
    started = threading.Event()
    cancel_seen = threading.Event()

    class FakeArchiveService:
        def create_archive(self, sources, plan, progress_callback=None, cancel_event=None):
            assert cancel_event is not None
            started.set()
            while not cancel_event.is_set():
                QTest.qWait(10)
            cancel_seen.set()
            raise CancelledError("Operacja zostala anulowana.")

    window = MainWindow(
        archive_service=FakeArchiveService(),
        save_file_dialog=lambda *args, **kwargs: (str(output), "Universal Compress Archive (*.uca)"),
    )
    qtbot.addWidget(window)
    window.show()
    window.add_source_paths([source])

    QTest.mouseClick(window.start_button, Qt.LeftButton)

    assert started.wait(0.5) is True

    window.close()

    assert cancel_seen.wait(0.5) is True
    qtbot.waitUntil(lambda: window.isVisible() is False, timeout=2000)


def test_cancelled_zip_does_not_leave_partial_archive_file(qtbot, tmp_path):
    source_a = tmp_path / "alpha.txt"
    source_b = tmp_path / "beta.txt"
    source_a.write_text("alpha", encoding="utf-8")
    source_b.write_text("beta", encoding="utf-8")
    output = tmp_path / "wynik.zip"
    window = MainWindow()
    qtbot.addWidget(window)
    cancel_event = threading.Event()
    sources = window._build_archive_sources()

    window.add_source_paths([source_a, source_b])
    sources = window._build_archive_sources()

    def on_progress(current, total, source):
        cancel_event.set()

    with pytest.raises(CancelledError, match="anulowana"):
        window._create_zip_archive(
            output,
            sources=sources,
            progress_callback=on_progress,
            cancel_event=cancel_event,
        )

    assert output.exists() is False
