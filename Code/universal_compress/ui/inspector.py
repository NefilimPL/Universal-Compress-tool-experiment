from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget


class InspectorPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("2. Ustaw kompresje")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Wybierz ustawienia po kolei. Kazde pole opisuje, jaki ma wplyw na rozmiar i czas pracy.")
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        settings_card = QFrame()
        settings_card.setObjectName("subCard")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(10)

        settings_title = QLabel("Szybkie ustawienia")
        settings_title.setObjectName("subCardTitle")
        settings_layout.addWidget(settings_title)

        self.mode_label = QLabel("Format archiwum")
        self.mode_label.setObjectName("settingLabel")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Archiwum UCA (domyslne)", "ZIP (zgodnosc)", "Media Studio"])
        settings_layout.addWidget(self.mode_label)
        settings_layout.addWidget(self.mode_combo)

        self.profile_label = QLabel("Tryb kompresji")
        self.profile_label.setObjectName("settingLabel")
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Zbalansowany", "Szybciej", "Mocniej kompresuj", "Archiwum"])
        settings_layout.addWidget(self.profile_label)
        settings_layout.addWidget(self.profile_combo)

        self.protection_label = QLabel("Zabezpieczenie")
        self.protection_label.setObjectName("settingLabel")
        self.protection_combo = QComboBox()
        self.protection_combo.addItems(["Brak", "Haslo dostepu", "Pelne szyfrowanie"])
        settings_layout.addWidget(self.protection_label)
        settings_layout.addWidget(self.protection_combo)

        self.explainer_label = QLabel(
            "Tryb Szybciej konczy prace szybciej. Mocniej kompresuj i Archiwum moga zmniejszyc rozmiar bardziej, ale zwykle trwaja dluzej."
        )
        self.explainer_label.setObjectName("hintLabel")
        self.explainer_label.setWordWrap(True)
        settings_layout.addWidget(self.explainer_label)
        root.addWidget(settings_card)

        summary_card = QFrame()
        summary_card.setObjectName("subCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setSpacing(6)

        summary_title = QLabel("3. Podsumowanie")
        summary_title.setObjectName("cardTitle")
        self.cost_label = QLabel("Szacowany koszt: niski")
        self.cost_label.setObjectName("costLabel")
        self.load_label = QLabel("Obciazenie sprzetu: niskie")
        self.load_label.setObjectName("selectionLabel")
        self.selection_label = QLabel("Zrodla: 0")
        self.selection_label.setObjectName("selectionLabel")
        self.format_hint_label = QLabel("Wynik: plik .uca z pelnym indeksem i funkcjami programu.")
        self.format_hint_label.setObjectName("selectionLabel")
        self.format_hint_label.setWordWrap(True)
        self.hint_label = QLabel("Dobry wybor do malych paczek i szybkich testow.")
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setWordWrap(True)

        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.cost_label)
        summary_layout.addWidget(self.load_label)
        summary_layout.addWidget(self.selection_label)
        summary_layout.addWidget(self.format_hint_label)
        summary_layout.addWidget(self.hint_label)
        root.addWidget(summary_card)

        progress_card = QFrame()
        progress_card.setObjectName("subCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 14, 14, 14)
        progress_layout.setSpacing(8)

        progress_title = QLabel("Postep zadania")
        progress_title.setObjectName("cardTitle")
        self.job_status_label = QLabel("Stan zadania: gotowe")
        self.job_status_label.setObjectName("selectionLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_detail_label = QLabel("Brak aktywnej kompresji.")
        self.progress_detail_label.setObjectName("hintLabel")
        self.progress_detail_label.setWordWrap(True)
        self.eta_label = QLabel("Pozostaly czas: --")
        self.eta_label.setObjectName("selectionLabel")
        self.last_output_label = QLabel("Ostatni wynik: brak")
        self.last_output_label.setObjectName("hintLabel")
        self.last_output_label.setWordWrap(True)

        progress_layout.addWidget(progress_title)
        progress_layout.addWidget(self.job_status_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_detail_label)
        progress_layout.addWidget(self.eta_label)
        progress_layout.addWidget(self.last_output_label)
        root.addWidget(progress_card)

    def set_cost_label(self, text: str) -> None:
        self.cost_label.setText(text)

    def set_selection_summary(self, source_count: int, total_bytes: int) -> None:
        size_mb = total_bytes / (1024 * 1024)
        self.selection_label.setText(f"Zrodla: {source_count}  |  Rozmiar: {size_mb:.2f} MB")

    def set_cost_hint(self, text: str) -> None:
        self.hint_label.setText(text)

    def set_load_label(self, text: str) -> None:
        self.load_label.setText(text)

    def set_explainer_text(self, text: str) -> None:
        self.explainer_label.setText(text)

    def set_format_hint(self, text: str) -> None:
        self.format_hint_label.setText(text)

    def set_job_status(self, text: str) -> None:
        self.job_status_label.setText(text)

    def set_progress_value(self, value: int) -> None:
        self.progress_bar.setValue(max(0, min(100, value)))

    def set_progress_detail(self, text: str) -> None:
        self.progress_detail_label.setText(text)

    def set_eta_text(self, text: str) -> None:
        self.eta_label.setText(text)

    def set_last_output(self, text: str) -> None:
        self.last_output_label.setText(text)
