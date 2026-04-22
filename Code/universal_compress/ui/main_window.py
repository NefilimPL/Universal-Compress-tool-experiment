from __future__ import annotations

import inspect
import queue
import threading
import time
import traceback
from pathlib import Path
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..archive.service import ArchiveService
from ..costs import classify_operation_cost
from ..media import MediaCompressionService
from ..models import ArchivePlan, ArchiveProtection, CancelledError, SourceItem
from .inspector import InspectorPanel
from .source_list import SourceListWidget
from .task_history import TaskHistoryWidget


class DropZoneFrame(QFrame):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        archive_service: ArchiveService | None = None,
        media_service: MediaCompressionService | None = None,
        save_file_dialog=None,
        choose_directory_dialog=None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Universal Compress V2")
        self.setAcceptDrops(True)
        self.resize(1440, 920)
        self.setMinimumSize(1180, 780)

        self._source_paths: list[Path] = []
        self.archive_service = archive_service or ArchiveService()
        self.media_service = media_service or MediaCompressionService()
        self._save_file_dialog = save_file_dialog or QFileDialog.getSaveFileName
        self._choose_directory_dialog = choose_directory_dialog or QFileDialog.getExistingDirectory
        self._job_events: queue.Queue[dict] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._job_cancel_event: threading.Event | None = None
        self._job_started_at: float | None = None
        self._job_output_path: Path | None = None
        self._job_mode_label = "kompresja"
        self._close_after_cancel = False

        self.add_files_button = QPushButton("Dodaj pliki")
        self.add_files_button.setObjectName("secondaryAction")
        self.add_folder_button = QPushButton("Dodaj folder")
        self.add_folder_button.setObjectName("secondaryAction")
        self.clear_button = QPushButton("Wyczysc")
        self.clear_button.setObjectName("secondaryAction")
        self.stop_button = QPushButton("Zatrzymaj")
        self.stop_button.setObjectName("dangerAction")
        self.stop_button.setEnabled(False)
        self.start_button = QPushButton("Przygotuj kompresje")
        self.start_button.setObjectName("primaryAction")

        self.source_list = SourceListWidget()
        self.inspector = InspectorPanel()
        self.inspector.setObjectName("panelShell")
        self.task_history = TaskHistoryWidget()
        self.task_history.setObjectName("panelShell")
        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.setWordWrap(True)
        self.activity_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_list.setSpacing(8)
        self.activity_list.addItem(QListWidgetItem("Interfejs gotowy. Dodaj zrodla, aby przygotowac nowe zadanie."))

        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._update_summary()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_job_events)
        self._poll_timer.start(50)

    def _build_ui(self) -> None:
        body = QWidget()
        body.setObjectName("windowBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        root.addWidget(self._build_top_bar())

        self.main_area = QWidget()
        self.main_columns_layout = QHBoxLayout(self.main_area)
        self.main_columns_layout.setContentsMargins(0, 0, 0, 0)
        self.main_columns_layout.setSpacing(18)
        self.main_columns_layout.addWidget(self._build_workspace_card(), 7)
        self.main_columns_layout.addWidget(self._build_sidebar(), 3)
        root.addWidget(self.main_area, 1)

        root.addWidget(self._build_queue_card())

        self.setCentralWidget(body)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Zacznij od dodania plikow lub folderow do glownego obszaru pracy.")

        menu = self.menuBar()
        menu.setNativeMenuBar(False)
        quick_actions = menu.addMenu("Plik")
        quick_actions.addAction(self._create_action("Dodaj pliki", self.choose_files))
        quick_actions.addAction(self._create_action("Dodaj folder", self.choose_folder))
        quick_actions.addSeparator()
        quick_actions.addAction(self._create_action("Wyczysc liste", self.clear_sources))

    def _build_top_bar(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("heroCard")

        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(20)

        copy_layout = QVBoxLayout()
        copy_layout.setSpacing(4)

        eyebrow = QLabel("UNIVERSAL COMPRESS V2")
        eyebrow.setObjectName("eyebrowLabel")
        title = QLabel("Nowe archiwum bez zgadywania")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "Dodaj wiele plikow naraz, ustaw kompresje po prawej i obserwuj kolejke na dole. Glowne kroki sa widoczne od razu."
        )
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)

        copy_layout.addWidget(eyebrow)
        copy_layout.addWidget(title)
        copy_layout.addWidget(subtitle)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(10)
        actions_layout.addWidget(self.add_files_button)
        actions_layout.addWidget(self.add_folder_button)
        actions_layout.addWidget(self.clear_button)
        actions_layout.addWidget(self.stop_button)
        actions_layout.addWidget(self.start_button)

        hero_layout.addLayout(copy_layout, 1)
        hero_layout.addWidget(actions_widget, 0, Qt.AlignTop)
        return hero

    def _build_workspace_card(self) -> QFrame:
        self.workspace_card = QFrame()
        self.workspace_card.setObjectName("sectionCard")
        self.workspace_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self.workspace_card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("1. Dodaj zrodla")
        title.setObjectName("panelTitle")
        subtitle = QLabel(
            "To jest glowny obszar pracy. Przeciagnij pliki, foldery albo archiwa, a potem sprawdz ustawienia po prawej stronie."
        )
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)

        self.dropzone_card = DropZoneFrame()
        self.dropzone_card.setObjectName("dropzoneCard")
        self.dropzone_card.setMinimumHeight(128)
        dropzone_layout = QVBoxLayout(self.dropzone_card)
        dropzone_layout.setContentsMargins(22, 20, 22, 20)
        dropzone_layout.setSpacing(6)

        self.dropzone_title = QLabel("Upusc pliki lub foldery")
        self.dropzone_title.setObjectName("dropzoneTitle")
        self.dropzone_hint = QLabel(
            "Przeciagnij dane tutaj albo uzyj przyciskow w gornej belce. Mozesz wrzucic wiele elementow jednoczesnie."
        )
        self.dropzone_hint.setObjectName("dropzoneHint")
        self.dropzone_hint.setWordWrap(True)
        self.dropzone_meta = QLabel("Najlepiej dodac wszystko tutaj, a ustawienia dopasowac dopiero w drugim kroku.")
        self.dropzone_meta.setObjectName("hintLabel")
        self.dropzone_meta.setWordWrap(True)

        dropzone_layout.addWidget(self.dropzone_title)
        dropzone_layout.addWidget(self.dropzone_hint)
        dropzone_layout.addWidget(self.dropzone_meta)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.source_count_chip = QLabel("0 zrodel")
        self.source_count_chip.setObjectName("statChip")
        self.total_size_chip = QLabel("0.00 MB")
        self.total_size_chip.setObjectName("statChip")
        stats_row.addWidget(self.source_count_chip)
        stats_row.addWidget(self.total_size_chip)
        stats_row.addStretch(1)

        self.source_list.setMinimumHeight(260)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.dropzone_card)
        layout.addLayout(stats_row)
        layout.addWidget(self.source_list, 1)
        return self.workspace_card

    def _build_sidebar(self) -> QWidget:
        self.sidebar_content = QWidget()
        self.sidebar_content.setObjectName("sidebarContent")

        layout = QVBoxLayout(self.sidebar_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        settings_card = QFrame()
        settings_card.setObjectName("sectionCard")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(20, 20, 20, 20)
        settings_layout.setSpacing(0)
        settings_layout.addWidget(self.inspector)

        layout.addWidget(settings_card)
        layout.addStretch(1)

        self.sidebar_widget = QScrollArea()
        self.sidebar_widget.setObjectName("sidebarWidget")
        self.sidebar_widget.setWidgetResizable(True)
        self.sidebar_widget.setFrameShape(QFrame.NoFrame)
        self.sidebar_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_widget.setMinimumWidth(360)
        self.sidebar_widget.setMaximumWidth(420)
        self.sidebar_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.sidebar_widget.setWidget(self.sidebar_content)
        return self.sidebar_widget

    def _build_queue_card(self) -> QFrame:
        self.queue_card = QFrame()
        self.queue_card.setObjectName("sectionCard")
        self.queue_card.setMaximumHeight(240)
        self.queue_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self.queue_card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("4. Kolejka i aktywnosc")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Dolny panel pokazuje, co juz czeka, co wlasnie ruszylo i jakie zdarzenia zapisala aplikacja.")
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)

        self.queue_tabs = QTabWidget()
        self.queue_tabs.setDocumentMode(True)
        self.queue_tabs.setMinimumHeight(132)
        self.queue_tabs.addTab(self.task_history, "Kolejka")
        self.queue_tabs.addTab(self.activity_list, "Aktywnosc")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.queue_tabs, 1)
        return self.queue_card

    def _connect_signals(self) -> None:
        self.add_files_button.clicked.connect(self.choose_files)
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.clear_button.clicked.connect(self.clear_sources)
        self.stop_button.clicked.connect(self._cancel_current_job)
        self.start_button.clicked.connect(self._start_compression)
        self.source_list.paths_dropped.connect(self.add_source_paths)
        self.dropzone_card.paths_dropped.connect(self.add_source_paths)
        self.inspector.mode_combo.currentTextChanged.connect(self._update_summary)
        self.inspector.profile_combo.currentTextChanged.connect(self._update_summary)
        self.inspector.protection_combo.currentTextChanged.connect(self._update_summary)

    def _create_action(self, label: str, handler) -> QAction:
        action = QAction(label, self)
        action.triggered.connect(handler)
        return action

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#windowBody {
                background: #f3efe8;
                color: #18161a;
                font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
            }
            QWidget#panelShell {
                background: transparent;
            }
            QScrollArea#sidebarWidget {
                background: transparent;
                border: none;
            }
            QLabel {
                color: #18161a;
                background: transparent;
            }
            QFrame#sectionCard, QFrame#subCard, QFrame#dropzoneCard {
                background: #fffaf4;
                border: 1px solid #e2d3c3;
                border-radius: 22px;
            }
            QFrame#heroCard {
                background: #1f232b;
                border: 1px solid #343b46;
                border-radius: 24px;
            }
            QFrame#dropzoneCard {
                background: #fcf6ef;
                border: 2px dashed #cf9a67;
            }
            QLabel#eyebrowLabel {
                color: #cbb79f;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#heroTitle {
                color: #fff7ed;
                font-size: 30px;
                font-weight: 750;
            }
            QLabel#heroSubtitle {
                color: #d9c8b2;
                font-size: 13px;
            }
            QLabel#panelTitle, QLabel#cardTitle {
                color: #18161a;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#panelSubtitle, QLabel#hintLabel {
                color: #6b5d52;
                font-size: 13px;
            }
            QLabel#dropzoneTitle {
                color: #1f232b;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#dropzoneHint {
                color: #3e342e;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#subCardTitle {
                color: #936134;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.4px;
                text-transform: uppercase;
            }
            QLabel#settingLabel {
                color: #3e342e;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#costLabel {
                font-size: 22px;
                font-weight: 800;
                color: #af5400;
            }
            QLabel#selectionLabel {
                font-size: 13px;
                color: #3b312d;
            }
            QLabel#statChip {
                background: #efe3d6;
                color: #58493f;
                border: 1px solid #decbb8;
                border-radius: 999px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 700;
            }
            QListWidget {
                background: #fffdf9;
                color: #18161a;
                border: 1px solid #ddccb7;
                border-radius: 16px;
                padding: 8px;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                padding: 12px 14px;
                border-radius: 12px;
                margin-bottom: 4px;
            }
            QListWidget::item:selected {
                background: #efe0d0;
                color: #18161a;
            }
            QComboBox {
                background: #fffdf9;
                color: #18161a;
                border: 1px solid #ddccb7;
                border-radius: 14px;
                padding: 7px 34px 7px 12px;
                min-height: 18px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid #ddccb7;
                background: #f0e2d4;
                border-top-right-radius: 14px;
                border-bottom-right-radius: 14px;
            }
            QProgressBar {
                background: #f0e5d8;
                color: #18161a;
                border: 1px solid #ddccb7;
                border-radius: 12px;
                min-height: 18px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #ec9640;
                border-radius: 11px;
            }
            QComboBox QAbstractItemView {
                background: #fffaf4;
                color: #18161a;
                border: 1px solid #ddccb7;
                selection-background-color: #efe0d0;
                selection-color: #18161a;
            }
            QPushButton {
                border-radius: 14px;
                padding: 11px 16px;
                font-weight: 700;
            }
            QPushButton#secondaryAction {
                background: #2b313b;
                color: #fff8ef;
                border: 1px solid #414957;
            }
            QPushButton#secondaryAction:hover {
                background: #363e4b;
            }
            QPushButton#primaryAction {
                background: #dd8a3d;
                color: #21160d;
                border: 1px solid #e4a364;
            }
            QPushButton#primaryAction:hover {
                background: #ea9750;
            }
            QPushButton#dangerAction {
                background: #6c2f2f;
                color: #fff8ef;
                border: 1px solid #9f5353;
            }
            QPushButton#dangerAction:hover {
                background: #834040;
            }
            QPushButton#primaryAction:pressed,
            QPushButton#secondaryAction:pressed,
            QPushButton#dangerAction:pressed {
                background: #171b22;
                color: #fff8ef;
            }
            QMenuBar {
                background: #efe5d9;
                color: #3b3028;
                border-bottom: 1px solid #ddccb7;
                padding: 4px 8px;
            }
            QMenuBar::item {
                background: transparent;
                color: #3b3028;
                padding: 8px 12px;
                border-radius: 8px;
            }
            QMenuBar::item:selected {
                background: #ead9c7;
            }
            QMenu {
                background: #fffaf4;
                color: #18161a;
                border: 1px solid #ddccb7;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 28px 8px 12px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: #efe0d0;
            }
            QTabWidget::pane {
                border: 1px solid #ddccb7;
                border-radius: 16px;
                background: #fffdf9;
                margin-top: 10px;
            }
            QTabBar::tab {
                background: #efe3d6;
                color: #5a4b41;
                border: 1px solid #ddccb7;
                padding: 8px 14px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                background: #fffdf9;
                color: #18161a;
            }
            QStatusBar {
                background: #efe5d9;
                color: #5d5147;
            }
            QStatusBar::item {
                border: none;
            }
            QScrollBar:vertical {
                background: #f1e4d7;
                width: 12px;
                margin: 2px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #c9aa8b;
                min-height: 28px;
                border-radius: 6px;
            }
            QScrollBar:horizontal {
                background: #f1e4d7;
                height: 12px;
                margin: 2px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #c9aa8b;
                min-width: 28px;
                border-radius: 6px;
            }
            """
        )

    def add_source_paths(self, paths: list[Path]) -> None:
        normalized: list[Path] = []
        known = {str(path) for path in self._source_paths}
        for path in paths:
            candidate = Path(path)
            if not candidate.exists():
                continue
            key = str(candidate)
            if key in known:
                continue
            normalized.append(candidate)
            known.add(key)

        if not normalized:
            return

        self._source_paths.extend(normalized)
        self.source_list.add_paths(normalized)
        self.statusBar().showMessage(f"Dodano {len(normalized)} zrodel do zadania.")
        self.task_history.prepend_event(f"Dodano {len(normalized)} zrodel do kolejki roboczej.")
        self._append_activity(f"Nowe zrodla: {', '.join(path.name or str(path) for path in normalized[:3])}")
        self._update_summary()

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Wybierz pliki do kompresji")
        self.add_source_paths([Path(path) for path in files])

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Wybierz folder do kompresji")
        if folder:
            self.add_source_paths([Path(folder)])

    def clear_sources(self) -> None:
        self._source_paths.clear()
        self.source_list.clear()
        self.statusBar().showMessage("Lista zrodel zostala wyczyszczona.")
        self.task_history.prepend_event("Wyczyszczono biezace zrodla zadania.")
        self._append_activity("Uzytkownik wyczyscil glowna liste zrodel.")
        self._update_summary()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            self.add_source_paths(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _append_activity(self, text: str) -> None:
        self.activity_list.insertItem(0, QListWidgetItem(text))

    def _set_job_feedback(
        self,
        *,
        status: str,
        detail: str,
        progress: int,
        eta_seconds: float | None = None,
        output_path: Path | None = None,
    ) -> None:
        self.inspector.set_job_status(f"Stan zadania: {status}")
        self.inspector.set_progress_value(progress)
        self.inspector.set_progress_detail(detail)
        self.inspector.set_eta_text(f"Pozostaly czas: {self._format_duration(eta_seconds)}")
        if output_path is not None:
            self.inspector.set_last_output(f"Ostatni wynik: {output_path.name}")
        QApplication.processEvents()

    def _format_duration(self, seconds: float | None) -> str:
        if seconds is None:
            return "--"

        rounded = max(0, int(round(seconds)))
        if rounded < 60:
            return f"{rounded} s"

        minutes, secs = divmod(rounded, 60)
        if minutes < 60:
            return f"{minutes} min {secs} s"

        hours, minutes = divmod(minutes, 60)
        return f"{hours} h {minutes} min"

    def _set_controls_enabled(self, enabled: bool) -> None:
        widgets = [
            self.add_files_button,
            self.add_folder_button,
            self.clear_button,
            self.start_button,
            self.inspector.mode_combo,
            self.inspector.profile_combo,
            self.inspector.protection_combo,
            self.source_list,
            self.dropzone_card,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)

    def _job_is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _launch_background_job(
        self,
        *,
        target,
        output_path: Path | None,
        mode_label: str,
        cancel_event: threading.Event,
    ) -> None:
        self._job_started_at = time.monotonic()
        self._job_output_path = output_path
        self._job_mode_label = mode_label
        self._job_cancel_event = cancel_event
        self._close_after_cancel = False
        self._set_controls_enabled(False)
        self._worker_thread = threading.Thread(target=target, daemon=True)
        self._worker_thread.start()

    def _queue_progress(self, current: int, total: int, detail: str) -> None:
        self._job_events.put({"type": "progress", "current": current, "total": total, "detail": detail})

    def _queue_done(self, **payload) -> None:
        self._job_events.put({"type": "done", **payload})

    def _queue_cancelled(self, **payload) -> None:
        self._job_events.put({"type": "cancelled", **payload})

    def _queue_error(self, message: str) -> None:
        self._job_events.put({"type": "error", "message": message, "traceback": traceback.format_exc()})

    def _queue_log(self, message: str) -> None:
        self._job_events.put({"type": "log", "message": message})

    def _poll_job_events(self) -> None:
        while True:
            try:
                item = self._job_events.get_nowait()
            except queue.Empty:
                break

            item_type = item["type"]
            if item_type == "progress":
                self._handle_job_progress(item)
            elif item_type == "cancelled":
                self._handle_job_cancelled(item)
            elif item_type == "done":
                self._handle_job_done(item)
            elif item_type == "error":
                self._handle_job_error(item)
            elif item_type == "log":
                self._append_activity(item["message"])

    def _handle_job_progress(self, item: dict) -> None:
        current = int(item["current"])
        total = max(1, int(item["total"]))
        detail = str(item["detail"])
        progress = int((current / total) * 100)

        eta_seconds = None
        if self._job_started_at is not None and current > 0:
            elapsed = time.monotonic() - self._job_started_at
            eta_seconds = max(0.0, (elapsed / current) * (total - current))

        self._set_job_feedback(
            status=self._job_mode_label,
            detail=detail,
            progress=progress,
            eta_seconds=eta_seconds,
            output_path=self._job_output_path,
        )
        self.statusBar().showMessage(detail)

    def _handle_job_done(self, item: dict) -> None:
        self._set_controls_enabled(True)
        outputs = [Path(path) for path in item.get("outputs", [])]
        output_path = None
        if outputs:
            output_path = outputs[-1]
        elif item.get("output_path"):
            output_path = Path(item["output_path"])

        detail = str(item.get("detail", "Zadanie zakonczone pomyslnie."))
        if output_path is not None:
            self._job_output_path = output_path

        self._set_job_feedback(
            status="zakonczono",
            detail=detail,
            progress=100,
            eta_seconds=0,
            output_path=self._job_output_path,
        )

        message = str(item.get("message", "Zadanie zakonczone pomyslnie."))
        self.statusBar().showMessage(message)
        self.task_history.prepend_event(message.rstrip("."))
        self._append_activity(str(item.get("activity", message)))
        self._finish_job()

    def _handle_job_error(self, item: dict) -> None:
        self._set_controls_enabled(True)
        message = str(item["message"])
        self._set_job_feedback(
            status="blad",
            detail=message,
            progress=0,
            output_path=self._job_output_path,
        )
        self.statusBar().showMessage(message)
        self._append_activity(f"Blad zadania: {message}")
        self._finish_job()

    def _handle_job_cancelled(self, item: dict) -> None:
        self._set_controls_enabled(True)
        detail = str(item.get("detail", "Operacja zostala anulowana."))
        message = str(item.get("message", "Operacja zostala anulowana."))
        status_message = f"Anulowano: {message}"
        self._set_job_feedback(
            status="anulowano",
            detail=detail,
            progress=self.inspector.progress_bar.value(),
            eta_seconds=0,
            output_path=self._job_output_path,
        )
        self.statusBar().showMessage(status_message)
        self.task_history.prepend_event(message.rstrip("."))
        self._append_activity(str(item.get("activity", message)))
        self._finish_job()

    def _finish_job(self) -> None:
        self._worker_thread = None
        self._job_cancel_event = None
        self._job_started_at = None
        should_close = self._close_after_cancel
        self._close_after_cancel = False
        if should_close:
            QTimer.singleShot(0, self.close)

    def _cancel_current_job(self, _checked: bool = False, *, reason: str = "manual") -> bool:
        if not self._job_is_running() or self._job_cancel_event is None:
            self.statusBar().showMessage("Brak aktywnego zadania do zatrzymania.")
            return False

        if self._job_cancel_event.is_set():
            self.statusBar().showMessage("Anulowanie zadania zostalo juz wyslane.")
            return True

        self._job_cancel_event.set()
        if reason == "close":
            detail = "Zamykanie okna anuluje aktywne zadanie i czeka na bezpieczne zatrzymanie."
            activity = "Zamykanie okna wyslalo prosbe anulowania biezacego zadania."
            status_message = "Anulowanie zadania przed zamknieciem okna..."
        else:
            detail = "Wyslano prosbe zatrzymania. Program konczy biezace operacje bezpiecznie."
            activity = "Uzytkownik poprosil o anulowanie biezacego zadania."
            status_message = "Wyslano prosbe zatrzymania zadania."

        self.stop_button.setEnabled(False)
        self._set_job_feedback(
            status="anulowanie",
            detail=detail,
            progress=self.inspector.progress_bar.value(),
            output_path=self._job_output_path,
        )
        self.statusBar().showMessage(status_message)
        self._append_activity(activity)
        return True

    def _run_archive_job(
        self,
        *,
        mode_text: str,
        sources: list[SourceItem],
        output_path: Path,
        cancel_event: threading.Event,
    ) -> None:
        try:
            if "ZIP" in mode_text:
                self._create_zip_archive(
                    output_path,
                    sources=sources,
                    cancel_event=cancel_event,
                    progress_callback=lambda current, total, source: self._queue_progress(
                        current,
                        total,
                        f"Kompresja {current}/{total}: {source.relative_path.as_posix()}",
                    ),
                )
            else:
                plan = ArchivePlan(output_path=output_path, protection=ArchiveProtection.NONE)
                self._invoke_with_optional_cancel(
                    self.archive_service.create_archive,
                    sources=sources,
                    plan=plan,
                    progress_callback=lambda current, total, source: self._queue_progress(
                        current,
                        total,
                        f"Kompresja {current}/{total}: {source.relative_path.as_posix()}",
                    ),
                    cancel_event=cancel_event,
                )
        except CancelledError as exc:
            output_path.unlink(missing_ok=True)
            self._queue_cancelled(
                message=str(exc),
                detail=f"Anulowano kompresje archiwum {output_path.name}.",
                activity=f"Anulowano tworzenie archiwum {output_path.name}.",
            )
            return
        except Exception as exc:
            self._queue_error(f"Nie udalo sie utworzyc archiwum: {exc}")
            return

        final_source = sources[-1].relative_path.as_posix()
        self._queue_done(
            output_path=str(output_path),
            message=f"Utworzono archiwum: {output_path.name}",
            detail=f"Zakonczono kompresje: {final_source}",
            activity=f"Zapisano archiwum do {output_path}.",
        )

    def _run_media_job(
        self,
        *,
        sources: list[SourceItem],
        output_dir: Path,
        profile_text: str,
        cancel_event: threading.Event,
    ) -> None:
        try:
            outputs = self._invoke_with_optional_cancel(
                self.media_service.compress_sources,
                [source.source_path for source in sources],
                output_dir,
                profile_text,
                progress_callback=self._queue_progress,
                log_callback=self._queue_log,
                cancel_event=cancel_event,
            )
        except CancelledError as exc:
            self._queue_cancelled(
                message=str(exc),
                detail="Anulowano kompresje mediow.",
                activity=f"Anulowano kompresje mediow do {output_dir}.",
            )
            return
        except Exception as exc:
            self._queue_error(f"Nie udalo sie skompresowac mediow: {exc}")
            return

        output_names = ", ".join(path.name for path in outputs[:3])
        if len(outputs) > 3:
            output_names += ", ..."
        self._queue_done(
            outputs=[str(path) for path in outputs],
            message=f"Zakonczono kompresje mediow: {len(outputs)} plikow.",
            detail=f"Gotowe pliki: {output_names}",
            activity=f"Zapisano media do {output_dir}.",
        )

    def _start_compression(self) -> None:
        if self._job_is_running():
            self.statusBar().showMessage("Poczekaj na zakonczenie biezacego zadania.")
            self._append_activity("Proba uruchomienia nowego zadania w trakcie aktywnej kompresji.")
            return

        if not self._source_paths:
            self._set_job_feedback(
                status="oczekiwanie na zrodla",
                detail="Dodaj przynajmniej jedno zrodlo przed rozpoczeciem kompresji.",
                progress=0,
            )
            self.statusBar().showMessage("Dodaj przynajmniej jedno zrodlo przed rozpoczeciem kompresji.")
            self._append_activity("Proba uruchomienia kompresji bez zrodel.")
            return

        mode_text = self.inspector.mode_combo.currentText()

        protection = self._selected_protection()
        if protection is not ArchiveProtection.NONE:
            self._set_job_feedback(
                status="w budowie",
                detail="Zabezpieczenia haslem beda gotowe po podpieciu prawdziwego przeplywu hasla.",
                progress=0,
            )
            self.statusBar().showMessage("Zabezpieczone archiwa beda podpiete po dodaniu prawdziwego przeplywu hasla.")
            self._append_activity("Wybrano zabezpieczenie, ale ten przeplyw nie jest jeszcze gotowy.")
            return

        self._set_job_feedback(
            status="przygotowanie",
            detail="Skanowanie wybranych zrodel i budowanie listy plikow.",
            progress=0,
        )
        sources = self._build_archive_sources()
        if not sources:
            self._set_job_feedback(
                status="brak plikow",
                detail="Nie znaleziono zadnych plikow do spakowania w wybranych zrodlach.",
                progress=0,
            )
            self.statusBar().showMessage("Nie znaleziono zadnych plikow do spakowania.")
            self._append_activity("Wybrane zrodla nie zawieraly plikow do kompresji.")
            return

        if "Media Studio" in mode_text:
            output_dir = self._choose_media_output_dir()
            if output_dir is None:
                self._set_job_feedback(
                    status="anulowano",
                    detail="Anulowano wybor folderu wyjsciowego dla mediow.",
                    progress=0,
                )
                self.statusBar().showMessage("Anulowano wybor folderu dla mediow.")
                self._append_activity("Anulowano zapis mediow.")
                return

            self._set_job_feedback(
                status="start mediow",
                detail=f"Przygotowano eksport mediow do {output_dir.name}.",
                progress=0,
                output_path=output_dir,
            )
            self._append_activity(f"Rozpoczeto przygotowanie mediow w {output_dir}.")
            cancel_event = threading.Event()
            self._launch_background_job(
                target=lambda: self._run_media_job(
                    sources=sources,
                    output_dir=output_dir,
                    profile_text=self.inspector.profile_combo.currentText(),
                    cancel_event=cancel_event,
                ),
                output_path=output_dir,
                mode_label="kompresja mediow",
                cancel_event=cancel_event,
            )
            return

        output_path = self._choose_output_path()
        if output_path is None:
            self._set_job_feedback(
                status="anulowano",
                detail="Anulowano wybor pliku wyjsciowego.",
                progress=0,
            )
            self.statusBar().showMessage("Anulowano wybor pliku wyjsciowego.")
            self._append_activity("Anulowano zapis archiwum.")
            return

        self._set_job_feedback(
            status="start",
            detail=f"Przygotowano zapis do {output_path.name}.",
            progress=0,
            output_path=output_path,
        )
        self._append_activity(f"Rozpoczeto przygotowanie archiwum {output_path.name}.")
        cancel_event = threading.Event()
        self._launch_background_job(
            target=lambda: self._run_archive_job(
                mode_text=mode_text,
                sources=sources,
                output_path=output_path,
                cancel_event=cancel_event,
            ),
            output_path=output_path,
            mode_label="kompresja",
            cancel_event=cancel_event,
        )

    def _selected_protection(self) -> ArchiveProtection:
        protection_text = self.inspector.protection_combo.currentText()
        mapping = {
            "Brak": ArchiveProtection.NONE,
            "Haslo dostepu": ArchiveProtection.PASSWORD_GATE,
            "Pelne szyfrowanie": ArchiveProtection.FULL_ENCRYPTION,
        }
        return mapping[protection_text]

    def _choose_output_path(self) -> Path | None:
        mode_text = self.inspector.mode_combo.currentText()
        if "ZIP" in mode_text:
            selected_path, _ = self._save_file_dialog(
                self,
                "Zapisz archiwum ZIP",
                str(self._default_output_path(".zip")),
                "Plik ZIP (*.zip)",
            )
            suffix = ".zip"
        else:
            selected_path, _ = self._save_file_dialog(
                self,
                "Zapisz archiwum UCA",
                str(self._default_output_path(".uca")),
                "Universal Compress Archive (*.uca)",
            )
            suffix = ".uca"

        if not selected_path:
            return None

        output_path = Path(selected_path)
        if output_path.suffix.lower() != suffix:
            output_path = output_path.with_suffix(suffix)
        return output_path

    def _choose_media_output_dir(self) -> Path | None:
        if len(self._source_paths) == 1:
            candidate = self._source_paths[0]
            default_dir = candidate.parent if candidate.is_file() else candidate
        else:
            default_dir = Path.cwd()

        selected_dir = self._choose_directory_dialog(
            self,
            "Wybierz folder dla skompresowanych mediow",
            str(default_dir),
        )
        if not selected_dir:
            return None
        return Path(selected_dir)

    def _default_output_path(self, suffix: str) -> Path:
        if len(self._source_paths) == 1:
            candidate = self._source_paths[0]
            base_name = candidate.stem if candidate.is_file() else candidate.name
            return candidate.parent / f"{base_name}{suffix}"
        return Path.cwd() / f"archive{suffix}"

    def _build_archive_sources(self) -> list[SourceItem]:
        sources: list[SourceItem] = []
        seen_paths: set[str] = set()

        for source_path in self._source_paths:
            source_path = Path(source_path)
            if source_path.is_file():
                self._append_source_item(
                    sources=sources,
                    seen_paths=seen_paths,
                    source_path=source_path,
                    relative_path=PurePosixPath(source_path.name),
                )
                continue

            if source_path.is_dir():
                for nested in sorted(source_path.rglob("*")):
                    if not nested.is_file():
                        continue
                    relative = PurePosixPath(source_path.name) / PurePosixPath(nested.relative_to(source_path).as_posix())
                    self._append_source_item(
                        sources=sources,
                        seen_paths=seen_paths,
                        source_path=nested,
                        relative_path=relative,
                    )

        return sources

    def _append_source_item(
        self,
        sources: list[SourceItem],
        seen_paths: set[str],
        source_path: Path,
        relative_path: PurePosixPath,
    ) -> None:
        normalized = relative_path.as_posix()
        if normalized in seen_paths:
            relative_path = self._dedupe_relative_path(relative_path, seen_paths)
            normalized = relative_path.as_posix()

        sources.append(
            SourceItem(
                source_path=source_path,
                relative_path=relative_path,
                size=source_path.stat().st_size,
            )
        )
        seen_paths.add(normalized)

    def _dedupe_relative_path(self, relative_path: PurePosixPath, seen_paths: set[str]) -> PurePosixPath:
        suffix = relative_path.suffix
        stem = relative_path.name[: -len(suffix)] if suffix else relative_path.name
        parent = relative_path.parent
        counter = 2

        while True:
            candidate_name = f"{stem}-{counter}{suffix}"
            candidate = parent / candidate_name if str(parent) != "." else PurePosixPath(candidate_name)
            if candidate.as_posix() not in seen_paths:
                return candidate
            counter += 1

    def _create_zip_archive(
        self,
        output_path: Path,
        sources: list[SourceItem],
        progress_callback=None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._ensure_not_cancelled(cancel_event)
            with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zip_file:
                total = len(sources)
                for index, source in enumerate(sources, start=1):
                    self._ensure_not_cancelled(cancel_event)
                    zip_file.write(source.source_path, arcname=source.relative_path.as_posix())
                    if progress_callback is not None:
                        progress_callback(index, total, source)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        return output_path

    def _ensure_not_cancelled(self, cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Operacja zostala anulowana.")

    def _invoke_with_optional_cancel(self, callable_obj, *args, cancel_event: threading.Event, **kwargs):
        signature = inspect.signature(callable_obj)
        if "cancel_event" in signature.parameters:
            kwargs["cancel_event"] = cancel_event
        return callable_obj(*args, **kwargs)

    def _measure_total_bytes(self) -> int:
        total_bytes = 0
        for path in self._source_paths:
            if path.is_file():
                total_bytes += path.stat().st_size
                continue
            if path.is_dir():
                for nested in path.rglob("*"):
                    if nested.is_file():
                        total_bytes += nested.stat().st_size
        return total_bytes

    def _update_summary(self) -> None:
        total_bytes = self._measure_total_bytes()
        source_count = len(self._source_paths)
        mode_text = self.inspector.mode_combo.currentText()
        profile_text = self.inspector.profile_combo.currentText()
        protection_text = self.inspector.protection_combo.currentText()
        media_mode = "Media Studio" in mode_text
        encrypted = protection_text != "Brak"
        cost = classify_operation_cost(total_bytes=total_bytes, encrypted=encrypted, media_mode=media_mode)
        cost_map = {
            "Low": "niski",
            "Medium": "sredni",
            "High": "wysoki",
        }
        self.inspector.set_cost_label(f"Szacowany koszt: {cost_map[cost.value]}")
        self.inspector.set_selection_summary(source_count, total_bytes)

        hint_map = {
            "Low": ("Obciazenie sprzetu: niskie", "Dobry wybor do malych paczek i szybkich testow."),
            "Medium": ("Obciazenie sprzetu: srednie", "Zadanie moze zajac chwile i wyrazniej obciazyc dysk albo procesor."),
            "High": ("Obciazenie sprzetu: wysokie", "To zadanie bedzie ciezsze. Przygotuj sie na dluzszy czas pracy i mocniejsze uzycie sprzetu."),
        }
        load_text, hint_text = hint_map[cost.value]
        self.inspector.set_load_label(load_text)
        self.inspector.set_cost_hint(hint_text)

        explainer_parts = []
        if "ZIP" in mode_text:
            explainer_parts.append("ZIP stawia na zgodnosc z innymi programami.")
            self.start_button.setText("Eksportuj ZIP")
            self.inspector.set_format_hint("Wynik: plik .zip zgodny z innymi programami i systemami.")
        elif media_mode:
            explainer_parts.append("Media Studio jest najlepsze dla audio i wideo.")
            self.start_button.setText("Uruchom Media Studio")
            self.inspector.set_format_hint("Wynik: tryb media przygotowuje eksport audio albo wideo i zuzywa wiecej zasobow.")
        else:
            explainer_parts.append("UCA daje najwiecej funkcji programu i pozostaje domyslnym wyborem.")
            self.start_button.setText("Utworz archiwum UCA")
            self.inspector.set_format_hint("Wynik: plik .uca z pelnym indeksem i funkcjami programu.")

        if profile_text == "Szybciej":
            explainer_parts.append("Tryb Szybciej konczy prace szybciej kosztem slabszego docisku.")
        elif profile_text == "Mocniej kompresuj":
            explainer_parts.append("Ten tryb probuje mocniej zmniejszyc rozmiar, ale zwykle trwa dluzej.")
        elif profile_text == "Archiwum":
            explainer_parts.append("Tryb Archiwum celuje w lepszy wynik kosztem czasu i obciazenia.")
        else:
            explainer_parts.append("Tryb Zbalansowany jest najbezpieczniejszy na start.")

        if protection_text == "Haslo dostepu":
            explainer_parts.append("Haslo dostepu blokuje otwarcie w aplikacji, ale jest lzejsze niz pelne szyfrowanie.")
        elif protection_text == "Pelne szyfrowanie":
            explainer_parts.append("Pelne szyfrowanie najmocniej chroni dane, ale najmocniej podnosi koszt zadania.")
        else:
            explainer_parts.append("Brak zabezpieczenia daje najszybsze wykonanie.")

        self.inspector.set_explainer_text(" ".join(explainer_parts))

        size_mb = total_bytes / (1024 * 1024)
        self.source_count_chip.setText(f"{source_count} zrodel")
        self.total_size_chip.setText(f"{size_mb:.2f} MB")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._job_is_running():
            self._close_after_cancel = True
            self._cancel_current_job(reason="close")
            event.ignore()
            return
        super().closeEvent(event)
