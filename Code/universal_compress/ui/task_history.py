from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class TaskHistoryWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.history_list = QListWidget()
        self.history_list.setWordWrap(True)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_list.setTextElideMode(Qt.ElideNone)
        self.history_list.setSpacing(8)
        self.history_list.setUniformItemSizes(False)

        for line in [
            "Gotowe do pracy",
            "Brak aktywnych zadan",
            "Dodaj pliki lub folder, aby przygotowac pierwsza operacje",
        ]:
            self.history_list.addItem(QListWidgetItem(line))

        layout.addWidget(self.history_list, 1)

    def prepend_event(self, text: str) -> None:
        self.history_list.insertItem(0, QListWidgetItem(text))
