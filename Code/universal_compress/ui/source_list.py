from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class SourceListWidget(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setSpacing(6)
        self.setUniformItemSizes(False)
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideMiddle)

    def add_paths(self, paths: list[Path]) -> None:
        existing = {self.item(index).data(Qt.UserRole) for index in range(self.count())}
        for path in paths:
            normalized = str(Path(path))
            if normalized in existing:
                continue

            kind = "Folder" if Path(path).is_dir() else "Plik"
            name = Path(path).name or normalized
            display = f"{name}\n{kind}: {normalized}"

            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, normalized)
            item.setToolTip(normalized)
            self.addItem(item)
            existing.add(normalized)

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
