from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .algorithms import AVAILABLE_ALGOS
from .constants import APP_NAME, APP_VERSION, CONTAINER_EXT, DEFAULT_CHUNK, QUEUE_POLL_MS
from .container import read_container_header
from .jobs import compress_job, decompress_job, estimate_output, verify_archive_job
from .error_logging import write_error_report, write_exception_report
from .models import SourceSpec
from .paths import LOGS_DIR, SETTINGS_FILE
from .tooltip import ToolTip
from .utils import ensure_dir, format_seconds, human_size, read_text_file
from .video import VIDEO_PROFILES, find_ffmpeg, install_ffmpeg_job, is_video_file, transcode_video_job
from .worker import Worker


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1180x860")
        self.minsize(900, 620)

        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.current_worker: Optional[Worker] = None
        self.progress_start_time = 0.0
        self.last_output_file: Optional[Path] = None
        self._tooltips: list[ToolTip] = []

        self._build_variables()
        ensure_dir(LOGS_DIR)
        self._build_ui()
        self._load_settings()
        self.apply_theme()
        self.log(f"Folder logów błędów: {LOGS_DIR}")
        self.after(QUEUE_POLL_MS, self._poll_queue)

    def report_callback_exception(self, exc, val, tb):
        log_path = write_exception_report(
            exc,
            val,
            tb,
            context="Nieobsłużony wyjątek w callbacku interfejsu Tkinter.",
        )
        self.status_var.set("Błąd krytyczny interfejsu.")
        self.log(f"Błąd krytyczny interfejsu. Raport zapisano do: {log_path}")
        messagebox.showerror(
            "Błąd krytyczny",
            f"Wystąpił nieobsłużony błąd interfejsu.\n\nRaport zapisano do:\n{log_path}",
        )

    def _attach_tooltip(self, widget, text: str):
        self._tooltips.append(ToolTip(widget, text))

    def _build_variables(self):
        self.file_path_var = tk.StringVar()
        self.decode_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.text_name_var = tk.StringVar(value="tekst_wejsciowy.txt")

        self.algo_mode_var = tk.StringVar(value="single")
        self.single_algo_var = tk.StringVar(value=AVAILABLE_ALGOS[0] if AVAILABLE_ALGOS else "")
        self.level_var = tk.IntVar(value=6)
        self.chunk_var = tk.StringVar(value="1 MB")
        self.file_mode_var = tk.StringVar(value="archive")
        self.video_profile_var = tk.StringVar(value="strong")
        self.dark_theme_var = tk.BooleanVar(value=False)

        self.overwrite_var = tk.BooleanVar(value=False)
        self.verify_hash_var = tk.BooleanVar(value=True)
        self.restore_mtime_var = tk.BooleanVar(value=True)
        self.open_folder_var = tk.BooleanVar(value=False)
        self.prefer_original_path_var = tk.BooleanVar(value=True)
        self.load_text_on_decode_var = tk.BooleanVar(value=True)

        self.auto_zlib_var = tk.BooleanVar(value="zlib" in AVAILABLE_ALGOS)
        self.auto_gzip_var = tk.BooleanVar(value="gzip" in AVAILABLE_ALGOS)
        self.auto_bz2_var = tk.BooleanVar(value="bz2" in AVAILABLE_ALGOS)
        self.auto_lzma_var = tk.BooleanVar(value="lzma" in AVAILABLE_ALGOS)

        self.status_var = tk.StringVar(value="Gotowe.")
        self.progress_text_var = tk.StringVar(value="0%")
        self.eta_var = tk.StringVar(value="Pozostały czas: —")
        self.input_size_var = tk.StringVar(value="Wejście: —")
        self.estimate_size_var = tk.StringVar(value="Szacowany wynik: —")
        self.actual_size_var = tk.StringVar(value="Ostatni wynik: —")
        self.header_info_var = tk.StringVar(value="Nagłówek archiwum: —")
        self.file_info_var = tk.StringVar(value="Plik: —")
        self.text_info_var = tk.StringVar(value="Tekst: 0 znaków / 0 B")

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        title = ttk.Label(
            self,
            text=f"{APP_NAME} — bezstratne kodowanie i dekodowanie plików / tekstu",
            font=("Segoe UI", 14, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))

        main = ttk.Panedwindow(self, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        left = ttk.Frame(main, padding=8)
        right = ttk.Frame(main, padding=0)
        main.add(left, weight=3)
        main.add(right, weight=2)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(left)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self._build_tab_file()
        self._build_tab_text()
        self._build_tab_decode()

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.right_canvas = tk.Canvas(right, highlightthickness=0, borderwidth=0)
        self.right_scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.right_canvas.yview)
        self.right_canvas.configure(yscrollcommand=self.right_scrollbar.set)
        self.right_canvas.grid(row=0, column=0, sticky="nsew")
        self.right_scrollbar.grid(row=0, column=1, sticky="ns")

        self.right_inner = ttk.Frame(self.right_canvas, padding=8)
        self.right_window = self.right_canvas.create_window((0, 0), window=self.right_inner, anchor="nw")
        self.right_inner.columnconfigure(0, weight=1)
        self.right_inner.bind("<Configure>", self._on_right_panel_configure)
        self.right_canvas.bind("<Configure>", self._on_right_canvas_configure)
        self.right_canvas.bind("<Enter>", self._bind_right_panel_mousewheel)
        self.right_canvas.bind("<Leave>", self._unbind_right_panel_mousewheel)

        self._build_settings(self.right_inner)
        self._build_status(self.right_inner)
        self._build_log(self.right_inner)

    def _on_right_panel_configure(self, _event=None):
        if hasattr(self, "right_canvas"):
            self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all"))

    def _on_right_canvas_configure(self, event):
        if hasattr(self, "right_window"):
            self.right_canvas.itemconfigure(self.right_window, width=event.width)

    def _bind_right_panel_mousewheel(self, _event=None):
        self.bind_all("<MouseWheel>", self._on_right_mousewheel)

    def _unbind_right_panel_mousewheel(self, _event=None):
        self.unbind_all("<MouseWheel>")

    def _on_right_mousewheel(self, event):
        if hasattr(self, "right_canvas") and event.delta:
            self.right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_tab_file(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Kodowanie pliku")

        input_label = ttk.Label(tab, text="Plik wejściowy:")
        input_label.grid(row=0, column=0, sticky="w", pady=4)
        input_entry = ttk.Entry(tab, textvariable=self.file_path_var)
        input_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        input_button = ttk.Button(tab, text="Wybierz...", command=self.choose_file)
        input_button.grid(row=0, column=2, pady=4)

        info_label = ttk.Label(tab, textvariable=self.file_info_var)
        info_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 4))
        hint_label = ttk.Label(
            tab,
            text="Domyślnie wynik zapisze się obok pliku wejściowego, chyba że wskażesz katalog wyjściowy po prawej.",
        )
        hint_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        estimate_button = ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_file)
        estimate_button.pack(side="left", padx=(0, 8))
        encode_button = ttk.Button(buttons, text="Koduj plik", command=self.start_encode_file)
        encode_button.pack(side="left")

        self._attach_tooltip(input_label, "Wskaż plik, który ma zostać zapisany do archiwum .pylc.")
        self._attach_tooltip(input_entry, "Możesz wkleić ścieżkę ręcznie albo wybrać plik przyciskiem obok.")
        self._attach_tooltip(input_button, "Otwórz okno wyboru pliku wejściowego.")
        self._attach_tooltip(info_label, "Tutaj program pokazuje nazwę pliku, jego rozmiar i pełną ścieżkę.")
        self._attach_tooltip(hint_label, "Krótka informacja o domyślnej lokalizacji pliku wynikowego.")
        self._attach_tooltip(estimate_button, "Policz przewidywany rozmiar archiwum bez pełnego kodowania.")
        self._attach_tooltip(encode_button, "Uruchom kompresję wybranego pliku z bieżącymi ustawieniami.")
    def _build_tab_text(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.notebook.add(tab, text="Kodowanie tekstu")

        row1 = ttk.Frame(tab)
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(1, weight=1)

        name_label = ttk.Label(row1, text="Nazwa tekstu / przyszłego pliku:")
        name_label.grid(row=0, column=0, sticky="w", pady=4)
        name_entry = ttk.Entry(row1, textvariable=self.text_name_var)
        name_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        load_button = ttk.Button(row1, text="Wczytaj TXT...", command=self.load_text_from_file)
        load_button.grid(row=0, column=2, pady=4)

        info_label = ttk.Label(tab, textvariable=self.text_info_var)
        info_label.grid(row=1, column=0, sticky="w", pady=(4, 4))

        text_frame = ttk.Frame(tab)
        text_frame.grid(row=2, column=0, sticky="nsew", pady=6)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.text_box = tk.Text(text_frame, wrap="word", undo=True, font=("Consolas", 11))
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_box.yview)
        self.text_box.configure(yscrollcommand=text_scroll.set)
        self.text_box.grid(row=0, column=0, sticky="nsew")
        text_scroll.grid(row=0, column=1, sticky="ns")
        self.text_box.bind("<<Modified>>", self.on_text_modified)

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="w", pady=(6, 0))
        clear_button = ttk.Button(buttons, text="Wyczyść", command=lambda: self.text_box.delete("1.0", "end"))
        clear_button.pack(side="left", padx=(0, 8))
        estimate_button = ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_text)
        estimate_button.pack(side="left", padx=(0, 8))
        encode_button = ttk.Button(buttons, text="Koduj tekst", command=self.start_encode_text)
        encode_button.pack(side="left")

        self._attach_tooltip(name_label, "Nazwa zapisywana w metadanych archiwum i używana po odzyskaniu tekstu jako nazwa pliku.")
        self._attach_tooltip(name_entry, "Wpisz nazwę, pod jaką tekst ma być identyfikowany po dekodowaniu.")
        self._attach_tooltip(load_button, "Wczytaj zawartość pliku TXT do pola tekstowego.")
        self._attach_tooltip(info_label, "Liczba znaków i rozmiar tekstu po zakodowaniu w UTF-8.")
        self._attach_tooltip(self.text_box, "Tutaj wpisujesz albo wklejasz tekst, który ma zostać skompresowany.")
        self._attach_tooltip(clear_button, "Usuń całą zawartość pola tekstowego.")
        self._attach_tooltip(estimate_button, "Policz przewidywany rozmiar archiwum dla bieżącego tekstu.")
        self._attach_tooltip(encode_button, "Zapisz tekst do archiwum .pylc z użyciem aktualnych ustawień.")
    def _build_tab_decode(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Dekodowanie")

        archive_label = ttk.Label(tab, text="Archiwum *.pylc:")
        archive_label.grid(row=0, column=0, sticky="w", pady=4)
        archive_entry = ttk.Entry(tab, textvariable=self.decode_path_var)
        archive_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        archive_button = ttk.Button(tab, text="Wybierz...", command=self.choose_archive)
        archive_button.grid(row=0, column=2, pady=4)

        header_label = ttk.Label(tab, textvariable=self.header_info_var, justify="left")
        header_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 6))
        hint_label = ttk.Label(
            tab,
            text="Jeśli zaznaczysz ‘Przywracaj do oryginalnej lokalizacji’, program spróbuje użyć ścieżki zapisanej w archiwum; w przeciwnym razie użyje katalogu wyjściowego lub folderu domyślnego.",
            wraplength=760,
            justify="left",
        )
        hint_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        header_button = ttk.Button(buttons, text="Czytaj nagłówek", command=self.load_archive_header)
        header_button.pack(side="left", padx=(0, 8))
        verify_button = ttk.Button(buttons, text="Test integralności", command=self.start_verify_archive)
        verify_button.pack(side="left", padx=(0, 8))
        decode_button = ttk.Button(buttons, text="Dekoduj", command=self.start_decode)
        decode_button.pack(side="left")

        self._attach_tooltip(archive_label, "Wskaż archiwum PyLossless, które ma zostać odczytane.")
        self._attach_tooltip(archive_entry, "Możesz wkleić ścieżkę archiwum ręcznie albo wybrać plik przyciskiem obok.")
        self._attach_tooltip(archive_button, "Otwórz okno wyboru archiwum .pylc.")
        self._attach_tooltip(header_label, "Tutaj pojawiają się metadane zapisane w nagłówku archiwum.")
        self._attach_tooltip(hint_label, "Wyjaśnienie, skąd program bierze docelową lokalizację po dekodowaniu.")
        self._attach_tooltip(header_button, "Wczytaj sam nagłówek archiwum bez pełnego dekodowania danych.")
        self._attach_tooltip(verify_button, "Sprawdź integralność archiwum bez zapisywania odzyskanego pliku.")
        self._attach_tooltip(decode_button, "Odzyskaj plik lub tekst z wybranego archiwum.")
    def _build_settings(self, parent):
        frm = ttk.LabelFrame(parent, text="Ustawienia", padding=10)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        output_label = ttk.Label(frm, text="Katalog wyjściowy:")
        output_label.grid(row=0, column=0, sticky="w", pady=4)
        output_entry = ttk.Entry(frm, textvariable=self.output_dir_var)
        output_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        output_button = ttk.Button(frm, text="Wybierz...", command=self.choose_output_dir)
        output_button.grid(row=0, column=2, pady=4)

        ttk.Separator(frm, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)

        mode_label = ttk.Label(frm, text="Tryb kompresji:")
        mode_label.grid(row=2, column=0, sticky="w", pady=4)
        row = ttk.Frame(frm)
        row.grid(row=2, column=1, columnspan=2, sticky="w")
        mode_single = ttk.Radiobutton(row, text="Jeden algorytm", variable=self.algo_mode_var, value="single")
        mode_single.pack(side="left", padx=(0, 8))
        mode_auto = ttk.Radiobutton(row, text="Minimum z wybranych", variable=self.algo_mode_var, value="auto")
        mode_auto.pack(side="left")

        algo_label = ttk.Label(frm, text="Algorytm:")
        algo_label.grid(row=3, column=0, sticky="w", pady=4)
        algo_combo = ttk.Combobox(frm, state="readonly", values=AVAILABLE_ALGOS, textvariable=self.single_algo_var)
        algo_combo.grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        level_label = ttk.Label(frm, text="Poziom:")
        level_label.grid(row=3, column=2, sticky="e", pady=4)
        level_spin = ttk.Spinbox(frm, from_=0, to=9, textvariable=self.level_var, width=6)
        level_spin.grid(row=3, column=2, sticky="w", padx=(54, 0), pady=4)

        auto_label = ttk.Label(frm, text="Auto-test algorytmów:")
        auto_label.grid(row=4, column=0, sticky="nw", pady=4)
        auto_box = ttk.Frame(frm)
        auto_box.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)
        auto_zlib = ttk.Checkbutton(auto_box, text="zlib", variable=self.auto_zlib_var)
        auto_zlib.pack(side="left", padx=(0, 8))
        auto_gzip = ttk.Checkbutton(auto_box, text="gzip", variable=self.auto_gzip_var)
        auto_gzip.pack(side="left", padx=(0, 8))
        auto_bz2 = ttk.Checkbutton(auto_box, text="bz2", variable=self.auto_bz2_var)
        auto_bz2.pack(side="left", padx=(0, 8))
        auto_lzma = ttk.Checkbutton(auto_box, text="lzma", variable=self.auto_lzma_var)
        auto_lzma.pack(side="left")

        chunk_label = ttk.Label(frm, text="Rozmiar porcji:")
        chunk_label.grid(row=5, column=0, sticky="w", pady=4)
        chunk_combo = ttk.Combobox(frm, state="readonly", values=["256 KB", "512 KB", "1 MB", "4 MB"], textvariable=self.chunk_var, width=12)
        chunk_combo.grid(row=5, column=1, sticky="w", padx=6, pady=4)

        ttk.Separator(frm, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)

        file_mode_label = ttk.Label(frm, text="Tryb pliku:")
        file_mode_label.grid(row=7, column=0, sticky="w", pady=4)
        file_mode_row = ttk.Frame(frm)
        file_mode_row.grid(row=7, column=1, columnspan=2, sticky="w")
        file_mode_archive = ttk.Radiobutton(file_mode_row, text="Archiwum .pylc", variable=self.file_mode_var, value="archive")
        file_mode_archive.pack(side="left", padx=(0, 8))
        file_mode_video = ttk.Radiobutton(file_mode_row, text="FFmpeg video", variable=self.file_mode_var, value="video")
        file_mode_video.pack(side="left")

        video_profile_label = ttk.Label(frm, text="Profil video:")
        video_profile_label.grid(row=8, column=0, sticky="nw", pady=4)
        video_profile_row = ttk.Frame(frm)
        video_profile_row.grid(row=8, column=1, columnspan=2, sticky="w", pady=4)
        video_profile_balanced = ttk.Radiobutton(video_profile_row, text="Balans", variable=self.video_profile_var, value="balanced")
        video_profile_balanced.pack(side="left", padx=(0, 8))
        video_profile_strong = ttk.Radiobutton(video_profile_row, text="Mocna", variable=self.video_profile_var, value="strong")
        video_profile_strong.pack(side="left", padx=(0, 8))
        video_profile_max = ttk.Radiobutton(video_profile_row, text="Max 720p", variable=self.video_profile_var, value="max")
        video_profile_max.pack(side="left")

        overwrite_cb = ttk.Checkbutton(frm, text="Nadpisuj istniejace pliki", variable=self.overwrite_var)
        overwrite_cb.grid(row=9, column=0, columnspan=3, sticky="w", pady=2)
        verify_cb = ttk.Checkbutton(frm, text="Weryfikuj SHA-256 przy dekodowaniu", variable=self.verify_hash_var)
        verify_cb.grid(row=10, column=0, columnspan=3, sticky="w", pady=2)
        restore_cb = ttk.Checkbutton(frm, text="Przywracaj znacznik czasu pliku po dekodowaniu", variable=self.restore_mtime_var)
        restore_cb.grid(row=11, column=0, columnspan=3, sticky="w", pady=2)
        original_path_cb = ttk.Checkbutton(frm, text="Przywracaj do oryginalnej lokalizacji, jesli istnieje", variable=self.prefer_original_path_var)
        original_path_cb.grid(row=12, column=0, columnspan=3, sticky="w", pady=2)
        load_text_cb = ttk.Checkbutton(frm, text="Jesli zrodlem byl tekst, po dekodowaniu zaladuj go tez do pola", variable=self.load_text_on_decode_var)
        load_text_cb.grid(row=13, column=0, columnspan=3, sticky="w", pady=2)
        open_folder_cb = ttk.Checkbutton(frm, text="Otworz folder po zakonczeniu", variable=self.open_folder_var)
        open_folder_cb.grid(row=14, column=0, columnspan=3, sticky="w", pady=2)
        theme_cb = ttk.Checkbutton(frm, text="Ciemny motyw", variable=self.dark_theme_var, command=self.apply_theme)
        theme_cb.grid(row=15, column=0, columnspan=3, sticky="w", pady=(2, 4))

        btns = ttk.Frame(frm)
        btns.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        cancel_button = ttk.Button(btns, text="Anuluj", command=self.cancel_current_job)
        cancel_button.pack(side="left")
        open_last_button = ttk.Button(btns, text="Otworz ostatni folder", command=self.open_last_output_folder)
        open_last_button.pack(side="left", padx=(8, 0))

        self._attach_tooltip(output_label, "Opcjonalny katalog, do którego program zapisze archiwa lub odzyskane pliki.")
        self._attach_tooltip(output_entry, "Gdy pole jest puste, używany jest katalog domyślny albo lokalizacja źródła.")
        self._attach_tooltip(output_button, "Wybierz folder wynikowy bez ręcznego wpisywania ścieżki.")
        self._attach_tooltip(mode_label, "Wybierz sposób wybierania algorytmu kompresji.")
        self._attach_tooltip(mode_single, "Użyj tylko jednego wskazanego algorytmu. Ten tryb jest szybszy i prostszy do porównania.")
        self._attach_tooltip(mode_auto, "Przetestuj zaznaczone algorytmy i zachowaj najmniejszy wynik. Zwykle daje lepszą kompresję kosztem czasu.")
        self._attach_tooltip(algo_label, "Algorytm używany w trybie 'Jeden algorytm'.")
        self._attach_tooltip(algo_combo, "Wybierz konkretny algorytm kompresji używany bez auto-testu.")
        self._attach_tooltip(level_label, "Poziom kompresji wpływa na szybkość i wielkość wyniku.")
        self._attach_tooltip(level_spin, "Wyższy poziom zwykle kompresuje mocniej, ale może działać wolniej.")
        self._attach_tooltip(auto_label, "Lista algorytmów sprawdzanych w trybie 'Minimum z wybranych'.")
        self._attach_tooltip(auto_zlib, "Szybki i uniwersalny algorytm z małym narzutem.")
        self._attach_tooltip(auto_gzip, "Format zgodny z GZIP, wygodny przy typowych danych tekstowych i plikowych.")
        self._attach_tooltip(auto_bz2, "Silniejsza kompresja dla części danych, zwykle kosztem szybkości.")
        self._attach_tooltip(auto_lzma, "Często daje najmniejsze pliki, ale bywa najwolniejszy i zużywa więcej pamięci.")
        self._attach_tooltip(chunk_label, "Rozmiar porcji danych przetwarzanych jednorazowo.")
        self._attach_tooltip(chunk_combo, "Wieksze porcje moga przyspieszyc prace, ale zwiekszaja uzycie pamieci.")
        self._attach_tooltip(file_mode_label, "Dla zwyklych plikow zostaw archiwum .pylc. Dla .ts/.mp4 wybierz FFmpeg video, aby mocniej zmniejszyc rozmiar.")
        self._attach_tooltip(file_mode_archive, "Zapisz plik bezstratnie do archiwum .pylc.")
        self._attach_tooltip(file_mode_video, "Przekoduj plik video stratnie przez FFmpeg. To daje znacznie mniejsze pliki niz zwykle pakowanie danych.")
        self._attach_tooltip(video_profile_label, "Profil ustala sile kompresji video.")
        self._attach_tooltip(video_profile_balanced, "Lagodniejsza kompresja H.264 z lepsza zgodnoscia.")
        self._attach_tooltip(video_profile_strong, "Mocniejsza kompresja H.265 bez zmiany rozdzielczosci.")
        self._attach_tooltip(video_profile_max, "Najmniejszy plik: H.265, nizszy bitrate audio i ograniczenie do 720p.")
        self._attach_tooltip(overwrite_cb, "Jesli plik wynikowy juz istnieje, zostanie nadpisany zamiast tworzenia kolejnej wersji.")
        self._attach_tooltip(verify_cb, "Po dekodowaniu porownaj sume SHA-256 z wartoscia zapisana w archiwum.")
        self._attach_tooltip(restore_cb, "Po odzyskaniu pliku sprobuj przywrocic jego oryginalny czas modyfikacji.")
        self._attach_tooltip(original_path_cb, "Jesli archiwum zna oryginalny folder i ten folder nadal istnieje, program sprobuje go uzyc.")
        self._attach_tooltip(load_text_cb, "Gdy archiwum powstalo z tekstu, odzyskany tekst zostanie takze wpisany do pola edycji.")
        self._attach_tooltip(open_folder_cb, "Po zakonczeniu operacji automatycznie otworz folder z wynikiem.")
        self._attach_tooltip(theme_cb, "Przelacz jasny i ciemny motyw aplikacji.")
        self._attach_tooltip(cancel_button, "Popros biezace zadanie o bezpieczne anulowanie.")
        self._attach_tooltip(open_last_button, "Otworz folder zawierajacy ostatnio zapisany plik wynikowy.")
    def _build_status(self, parent):
        frm = ttk.LabelFrame(parent, text="Status i rozmiary", padding=10)
        frm.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, textvariable=self.status_var, wraplength=380, justify="left").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        ttk.Label(frm, textvariable=self.progress_text_var).grid(row=2, column=0, sticky="w")
        ttk.Label(frm, textvariable=self.eta_var).grid(row=3, column=0, sticky="w", pady=(2, 6))
        ttk.Label(frm, textvariable=self.input_size_var).grid(row=4, column=0, sticky="w", pady=1)
        ttk.Label(frm, textvariable=self.estimate_size_var).grid(row=5, column=0, sticky="w", pady=1)
        ttk.Label(frm, textvariable=self.actual_size_var).grid(row=6, column=0, sticky="w", pady=1)

    def _build_log(self, parent):
        frm = ttk.LabelFrame(parent, text="Dziennik", padding=10)
        frm.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        parent.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        log_frame = ttk.Frame(frm)
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_box = tk.Text(log_frame, height=16, wrap="word", state="disabled", font=("Consolas", 10))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def get_chunk_size(self) -> int:
        mapping = {
            "256 KB": 256 * 1024,
            "512 KB": 512 * 1024,
            "1 MB": 1024 * 1024,
            "4 MB": 4 * 1024 * 1024,
        }
        return mapping.get(self.chunk_var.get().strip().upper().replace("MB", " MB").replace("KB", " KB"), DEFAULT_CHUNK)

    def get_auto_algos(self) -> list[str]:
        algos = []
        if self.auto_zlib_var.get() and "zlib" in AVAILABLE_ALGOS:
            algos.append("zlib")
        if self.auto_gzip_var.get() and "gzip" in AVAILABLE_ALGOS:
            algos.append("gzip")
        if self.auto_bz2_var.get() and "bz2" in AVAILABLE_ALGOS:
            algos.append("bz2")
        if self.auto_lzma_var.get() and "lzma" in AVAILABLE_ALGOS:
            algos.append("lzma")
        return algos

    def is_video_mode(self) -> bool:
        return self.file_mode_var.get() == "video"

    def ensure_ffmpeg_ready(self) -> bool:
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path:
            self.log(f"Wykryto FFmpeg: {ffmpeg_path}")
            return True

        should_install = messagebox.askyesno(
            "FFmpeg",
            "Nie znaleziono FFmpeg w PATH.\n\nCzy chcesz sprobowac zainstalowac go teraz przez winget?",
        )
        if not should_install:
            self.log("FFmpeg nie jest dostepny. Uzytkownik pominol instalacje.")
            return False

        self.start_worker(
            "install_ffmpeg",
            install_ffmpeg_job,
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )
        return False

    def apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        if self.dark_theme_var.get():
            bg = "#11161c"
            panel = "#1b2430"
            field = "#0d1117"
            fg = "#e6edf3"
            accent = "#3b82f6"
            border = "#2f3945"
            select_bg = "#1d4ed8"
        else:
            bg = "#f3f5f7"
            panel = "#ffffff"
            field = "#ffffff"
            fg = "#111827"
            accent = "#2563eb"
            border = "#cbd5e1"
            select_bg = "#93c5fd"

        self.configure(bg=bg)
        if hasattr(self, "right_canvas"):
            self.right_canvas.configure(bg=bg, highlightbackground=border, highlightcolor=accent)
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground=fg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background=panel, foreground=fg, bordercolor=border, focusthickness=1, focuscolor=accent)
        style.map("TButton", background=[("active", accent)], foreground=[("active", "#ffffff")])
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TEntry", fieldbackground=field, foreground=fg, bordercolor=border)
        style.configure("TCombobox", fieldbackground=field, foreground=fg, background=panel, bordercolor=border, arrowcolor=fg)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)], selectbackground=[("readonly", field)], selectforeground=[("readonly", fg)])
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=panel, foreground=fg, padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", "#ffffff")])
        style.configure("TPanedwindow", background=bg)
        style.configure("TSeparator", background=border)
        style.configure("Horizontal.TProgressbar", troughcolor=field, background=accent, bordercolor=border)

        self.option_add("*TCombobox*Listbox*Background", field)
        self.option_add("*TCombobox*Listbox*Foreground", fg)
        self.option_add("*TCombobox*Listbox*selectBackground", accent)
        self.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")

        if hasattr(self, "text_box"):
            self.text_box.configure(
                bg=field,
                fg=fg,
                insertbackground=fg,
                selectbackground=select_bg,
                selectforeground="#ffffff" if self.dark_theme_var.get() else fg,
                highlightbackground=border,
                highlightcolor=accent,
            )
        if hasattr(self, "log_box"):
            self.log_box.configure(
                bg=field,
                fg=fg,
                insertbackground=fg,
                selectbackground=select_bg,
                selectforeground="#ffffff" if self.dark_theme_var.get() else fg,
                highlightbackground=border,
                highlightcolor=accent,
            )

    def choose_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik do zakodowania")
        if path:
            self.file_path_var.set(path)
            self.update_file_info()

    def choose_archive(self):
        path = filedialog.askopenfilename(
            title="Wybierz archiwum do dekodowania",
            filetypes=[("PyLossless (*.pylc)", f"*{CONTAINER_EXT}"), ("Wszystkie pliki", "*")],
        )
        if path:
            self.decode_path_var.set(path)
            self.load_archive_header()

    def choose_output_dir(self):
        path = filedialog.askdirectory(title="Wybierz katalog wyjściowy")
        if path:
            self.output_dir_var.set(path)

    def load_text_from_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik tekstowy")
        if not path:
            return
        try:
            text, encoding = read_text_file(Path(path))
        except Exception as exc:
            log_path = write_error_report(
                title="Błąd wczytywania pliku tekstowego",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context=f"Nie udało się wczytać pliku tekstowego: {path}",
            )
            self.log(f"Nie udało się wczytać tekstu z pliku: {path}")
            self.log(f"Raport błędu zapisano do: {log_path}")
            messagebox.showerror(
                "Błąd",
                f"Nie udało się wczytać tekstu z pliku:\n{exc}\n\nRaport zapisano do:\n{log_path}",
            )
            return

        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)
        self.text_name_var.set(Path(path).name)
        self.on_text_modified()
        self.log(f"Wczytano plik tekstowy ({encoding}): {path}")

    def update_file_info(self):
        path_str = self.file_path_var.get().strip()
        if not path_str:
            self.file_info_var.set("Plik: —")
            self.input_size_var.set("Wejście: —")
            return

        p = Path(path_str)
        if not p.exists():
            self.file_info_var.set("Plik: wskazana ścieżka nie istnieje.")
            self.input_size_var.set("Wejście: —")
            return

        size = p.stat().st_size
        self.file_info_var.set(f"Plik: {p.name} | {human_size(size)} | {p}")
        self.input_size_var.set(f"Wejście: {human_size(size)}")

    def on_text_modified(self, event=None):
        try:
            self.text_box.edit_modified(False)
        except tk.TclError:
            pass
        text = self.text_box.get("1.0", "end-1c")
        char_count = len(text)
        byte_count = len(text.encode("utf-8"))
        self.text_info_var.set(f"Tekst: {char_count} znaków / {human_size(byte_count)}")
        self.input_size_var.set(f"Wejście: {human_size(byte_count)}")

    def load_archive_header(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            return
        try:
            header, _ = read_container_header(Path(path_str))
            self.header_info_var.set("\n".join([
                f"Nazwa oryginalna: {header.get('original_name', '—')}",
                f"Typ źródła: {header.get('source_mode', '—')}",
                f"Algorytm: {header.get('algorithm', '—')} | poziom {header.get('level', '—')}",
                f"Rozmiar oryginału: {human_size(int(header.get('original_size') or 0))}",
                f"Oryginalna lokalizacja: {header.get('original_parent') or '—'}",
            ]))
        except Exception as e:
            self.header_info_var.set(f"Nie udało się odczytać nagłówka: {e}")

    def get_file_source(self) -> SourceSpec:
        path_str = self.file_path_var.get().strip()
        if not path_str:
            raise ValueError("Wybierz plik wejściowy.")
        p = Path(path_str)
        if not p.exists() or not p.is_file():
            raise ValueError("Wskazany plik nie istnieje lub nie jest plikiem.")
        return SourceSpec(mode="file", file_path=p, text_bytes=None, text_name=p.name)

    def get_text_source(self) -> SourceSpec:
        text = self.text_box.get("1.0", "end-1c")
        data = text.encode("utf-8")
        if not data and text == "":
            raise ValueError("Pole tekstowe jest puste.")
        name = self.text_name_var.get().strip() or "tekst_wejsciowy.txt"
        return SourceSpec(mode="text", file_path=None, text_bytes=data, text_name=name, text_encoding="utf-8")

    def reset_progress(self):
        self.progress["value"] = 0
        self.progress_text_var.set("0%")
        self.eta_var.set("Pozostały czas: —")
        self.progress_start_time = time.time()

    def update_progress(self, done: int, total: int, phase: str):
        total = max(total, 1)
        pct = min(100.0, (done / total) * 100.0)
        self.progress["value"] = pct
        self.progress_text_var.set(f"{pct:5.1f}% | {phase}")

        elapsed = max(0.001, time.time() - self.progress_start_time)
        speed = done / elapsed
        remaining = (total - done) / speed if speed > 0 else float("inf")
        self.eta_var.set(f"Pozostały czas: {format_seconds(remaining)} | {human_size(speed)}/s")

    def start_worker(self, task: str, fn: Callable, **kwargs):
        if self.current_worker and self.current_worker.is_alive():
            messagebox.showwarning("Uwaga", "Inne zadanie jest już w toku.")
            return
        self.cancel_event.clear()
        self.reset_progress()
        self.status_var.set("Przetwarzanie…")
        self.current_worker = Worker(self, task, fn, **kwargs)
        self.current_worker.start()

    def start_encode_file(self):
        try:
            source = self.get_file_source()
        except Exception as e:
            messagebox.showerror("Blad", str(e))
            return

        if self.is_video_mode():
            assert source.file_path is not None
            if not is_video_file(source.file_path):
                messagebox.showerror("Blad", "Tryb FFmpeg video dziala tylko dla plikow .ts, .mp4 i innych formatow video.")
                return
            if not self.ensure_ffmpeg_ready():
                return

            self.start_worker(
                "transcode_video",
                transcode_video_job,
                source_path=source.file_path,
                output_dir=self.output_dir_var.get().strip() or None,
                overwrite=self.overwrite_var.get(),
                profile=self.video_profile_var.get(),
                cancel_event=self.cancel_event,
                progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
                log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
            )
            return

        self.start_worker(
            "encode_file",
            compress_job,
            source=source,
            output_dir=self.output_dir_var.get().strip() or None,
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_encode_text(self):
        try:
            source = self.get_text_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "encode_text",
            compress_job,
            source=source,
            output_dir=self.output_dir_var.get().strip() or None,
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_decode(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            messagebox.showerror("Błąd", "Wybierz archiwum do dekodowania.")
            return

        arc = Path(path_str)
        if not arc.exists():
            messagebox.showerror("Błąd", "Archiwum nie istnieje.")
            return

        self.start_worker(
            "decode",
            decompress_job,
            archive_path=arc,
            output_dir=self.output_dir_var.get().strip() or None,
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            prefer_original_path=self.prefer_original_path_var.get(),
            verify_hash=self.verify_hash_var.get(),
            restore_mtime=self.restore_mtime_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
            load_text_to_memory=self.load_text_on_decode_var.get(),
        )

    def start_verify_archive(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            messagebox.showerror("Błąd", "Wybierz archiwum do sprawdzenia.")
            return

        arc = Path(path_str)
        if not arc.exists():
            messagebox.showerror("Błąd", "Archiwum nie istnieje.")
            return

        self.start_worker(
            "verify",
            verify_archive_job,
            archive_path=arc,
            chunk_size=self._chunk_value(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_estimate_from_file(self):
        try:
            source = self.get_file_source()
        except Exception as e:
            messagebox.showerror("Blad", str(e))
            return

        if self.is_video_mode():
            assert source.file_path is not None
            if not is_video_file(source.file_path):
                messagebox.showerror("Blad", "Tryb FFmpeg video dziala tylko dla plikow .ts, .mp4 i innych formatow video.")
                return
            messagebox.showinfo(
                "Informacja",
                "Szacowanie rozmiaru nie jest jeszcze dostepne dla transkodowania video FFmpeg. Uzyj przycisku 'Koduj plik'.",
            )
            return

        self.start_worker(
            "estimate",
            estimate_output,
            source=source,
            chunk_size=self._chunk_value(),
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
        )

    def start_estimate_from_text(self):
        try:
            source = self.get_text_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "estimate",
            estimate_output,
            source=source,
            chunk_size=self._chunk_value(),
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
        )

    def cancel_current_job(self):
        if self.current_worker and self.current_worker.is_alive():
            self.cancel_event.set()
            self.status_var.set("Anulowanie…")
            self.log("Wysłano żądanie anulowania zadania.")

    def open_last_output_folder(self):
        if not self.last_output_file:
            messagebox.showinfo("Informacja", "Brak ostatniego pliku wynikowego.")
            return
        self.open_folder(self.last_output_file.parent)

    def open_folder(self, path: Path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showwarning("Uwaga", f"Nie udało się otworzyć folderu:\n{e}")

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                t = item.get("type")

                if t == "progress":
                    self.update_progress(item["done"], item["total"], item["phase"])
                elif t == "log":
                    self.log(item["message"])
                elif t == "done":
                    self.handle_done(item)
                elif t == "error":
                    self.handle_error(item)
                elif t == "cancelled":
                    self.handle_cancelled(item)

        except queue.Empty:
            pass

        self.after(QUEUE_POLL_MS, self._poll_queue)

    def handle_done(self, item: dict):
        task = item["task"]
        result = item["result"]
        elapsed = item.get("elapsed", 0.0)
        self.current_worker = None

        if task == "estimate":
            best_algo = result["best_algo"]
            best_size = result["best_size"]
            kind = result["kind"]
            details = ", ".join(f"{k.upper()}: {human_size(v)}" for k, v in result["results"].items())
            self.estimate_size_var.set(
                f"Szacowany wynik: {human_size(best_size)} | najlepszy: {best_algo.upper()} | tryb: {'dokładny' if kind == 'exact' else 'z próbki'}"
            )
            self.status_var.set(f"Oszacowanie gotowe w {elapsed:.1f}s")
            self.log(f"Oszacowanie ({kind}): {details}")
            return

        if task == "install_ffmpeg":
            ffmpeg_path = result.get("path") or "ffmpeg.exe"
            info_text = "FFmpeg jest gotowy do uzycia."
            if result.get("already_present"):
                info_text = "FFmpeg byl juz zainstalowany i zostal poprawnie wykryty."
            self.estimate_size_var.set("Szacowany wynik: -")
            self.status_var.set(f"FFmpeg gotowy w {elapsed:.1f}s")
            self.log(f"{info_text} Lokalizacja: {ffmpeg_path}")
            messagebox.showinfo(
                "FFmpeg",
                f"{info_text}\n\nWykryta lokalizacja:\n{ffmpeg_path}",
            )
            return

        if task == "transcode_video":
            self.last_output_file = Path(result["dest"])
            profile_meta = VIDEO_PROFILES.get(result.get("profile", ""), {})
            profile_label = profile_meta.get("label", result.get("profile", "video"))
            self.actual_size_var.set(
                f"Ostatni wynik: {human_size(result['size'])} | kodek: {result['algorithm']} | wspolczynnik: {result['ratio']:.2f}%"
            )
            self.estimate_size_var.set("Szacowany wynik: -")
            self.status_var.set(f"Transkodowanie video zakonczone w {elapsed:.1f}s")
            self.log(
                f"Zapisano video: {result['dest']} | wejscie {human_size(result['source_size'])} -> wyjscie {human_size(result['size'])} | profil {profile_label}"
            )
            if self.open_folder_var.get() and self.last_output_file:
                self.open_folder(self.last_output_file.parent)
            return

        if task in {"encode_file", "encode_text"}:
            self.last_output_file = Path(result["dest"])
            self.actual_size_var.set(
                f"Ostatni wynik: {human_size(result['size'])} | algorytm: {result['algorithm'].upper()} | współczynnik: {result['ratio']:.2f}%"
            )
            self.estimate_size_var.set("Szacowany wynik: —")
            self.status_var.set(f"Kodowanie zakończone w {elapsed:.1f}s")
            self.log(
                f"Zapisano: {result['dest']} | wejście {human_size(result['source_size'])} -> wyjście {human_size(result['size'])} | {result['algorithm'].upper()}"
            )
            if self.open_folder_var.get() and self.last_output_file:
                self.open_folder(self.last_output_file.parent)
            return

        if task == "decode":
            self.last_output_file = Path(result["dest"])
            self.actual_size_var.set(
                f"Ostatni wynik: {human_size(result['size'])} | zdekompresowano algorytmem: {result['algorithm'].upper()}"
            )
            self.status_var.set(f"Dekodowanie zakończone w {elapsed:.1f}s")
            self.log(f"Odzyskano plik: {result['dest']}")

            if result.get("source_mode") == "text" and result.get("text") is not None and self.load_text_on_decode_var.get():
                self.text_box.delete("1.0", "end")
                self.text_box.insert("1.0", result["text"])
                self.on_text_modified()
                self.notebook.select(1)
                self.log("Załadowano odzyskany tekst do pola tekstowego.")

            if self.open_folder_var.get() and self.last_output_file:
                self.open_folder(self.last_output_file.parent)
            return

        if task == "verify":
            ok = result["ok"]
            self.status_var.set(f"Test integralności zakończony w {elapsed:.1f}s")
            self.log(
                "Test integralności: "
                + ("OK" if ok else "NIEPOWODZENIE")
                + f" | oczekiwany SHA-256: {result['expected_hash']} | obliczony: {result['actual_hash']}"
            )
            messagebox.showinfo(
                "Test integralności",
                "Integralność potwierdzona." if ok else "Integralność nie została potwierdzona. Sprawdź dziennik.",
            )
            return

    def handle_error(self, item: dict):
        self.current_worker = None
        self.status_var.set(f"Błąd: {item['message']}")
        if item.get("traceback"):
            self.log(item["traceback"])
        log_path = write_error_report(
            title=f"Błąd zadania: {item.get('task', 'nieznane')}",
            message=item["message"],
            traceback_text=item.get("traceback", ""),
            context="Wyjątek przechwycony w wątku roboczym i przekazany do GUI.",
            extra_lines=[f"Czas zadania: {item.get('elapsed', 0.0):.3f} s"],
        )
        self.log(f"Raport błędu zapisano do: {log_path}")
        messagebox.showerror(
            "Błąd",
            f"{item['message']}\n\nRaport zapisano do:\n{log_path}",
        )

    def handle_cancelled(self, item: dict):
        self.current_worker = None
        self.status_var.set("Operacja anulowana.")
        self.log(item.get("message", "Operacja anulowana."))

    def _chunk_value(self) -> int:
        value = self.chunk_var.get().strip().upper()
        mapping = {
            "256 KB": 256 * 1024,
            "512 KB": 512 * 1024,
            "1 MB": 1024 * 1024,
            "4 MB": 4 * 1024 * 1024,
        }
        return mapping.get(value, DEFAULT_CHUNK)

    def _load_settings(self):
        if not SETTINGS_FILE.exists():
            self.update_file_info()
            self.on_text_modified()
            return

        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.output_dir_var.set(data.get("output_dir", ""))
            self.file_mode_var.set(data.get("file_mode", "archive") if data.get("file_mode", "archive") in {"archive", "video"} else "archive")
            if data.get("video_profile") in VIDEO_PROFILES:
                self.video_profile_var.set(data.get("video_profile"))
            self.dark_theme_var.set(bool(data.get("dark_theme", False)))
            self.algo_mode_var.set(data.get("algo_mode", "single"))
            if data.get("single_algo") in AVAILABLE_ALGOS:
                self.single_algo_var.set(data.get("single_algo"))
            self.level_var.set(int(data.get("level", 6)))
            self.chunk_var.set(data.get("chunk", "1 MB"))
            self.overwrite_var.set(bool(data.get("overwrite", False)))
            self.verify_hash_var.set(bool(data.get("verify_hash", True)))
            self.restore_mtime_var.set(bool(data.get("restore_mtime", True)))
            self.prefer_original_path_var.set(bool(data.get("prefer_original_path", True)))
            self.load_text_on_decode_var.set(bool(data.get("load_text_on_decode", True)))
            self.open_folder_var.set(bool(data.get("open_folder", False)))
            self.auto_zlib_var.set(bool(data.get("auto_zlib", self.auto_zlib_var.get())))
            self.auto_gzip_var.set(bool(data.get("auto_gzip", self.auto_gzip_var.get())))
            self.auto_bz2_var.set(bool(data.get("auto_bz2", self.auto_bz2_var.get())))
            self.auto_lzma_var.set(bool(data.get("auto_lzma", self.auto_lzma_var.get())))
        except Exception as exc:
            log_path = write_error_report(
                title="Błąd wczytywania ustawień",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context="Wyjątek podczas odczytu pliku ustawień aplikacji.",
            )
            self.log(f"Nie udało się wczytać ustawień: {exc}")
            self.log(f"Raport błędu zapisano do: {log_path}")

        self.update_file_info()
        self.on_text_modified()

    def _save_settings(self):
        data = {
            "output_dir": self.output_dir_var.get(),
            "file_mode": self.file_mode_var.get(),
            "video_profile": self.video_profile_var.get(),
            "dark_theme": self.dark_theme_var.get(),
            "algo_mode": self.algo_mode_var.get(),
            "single_algo": self.single_algo_var.get(),
            "level": self.level_var.get(),
            "chunk": self.chunk_var.get(),
            "overwrite": self.overwrite_var.get(),
            "verify_hash": self.verify_hash_var.get(),
            "restore_mtime": self.restore_mtime_var.get(),
            "prefer_original_path": self.prefer_original_path_var.get(),
            "load_text_on_decode": self.load_text_on_decode_var.get(),
            "open_folder": self.open_folder_var.get(),
            "auto_zlib": self.auto_zlib_var.get(),
            "auto_gzip": self.auto_gzip_var.get(),
            "auto_bz2": self.auto_bz2_var.get(),
            "auto_lzma": self.auto_lzma_var.get(),
        }
        try:
            ensure_dir(SETTINGS_FILE.parent)
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            log_path = write_error_report(
                title="Błąd zapisu ustawień",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context="Wyjątek podczas zapisu pliku ustawień aplikacji.",
            )
            self.log(f"Nie udało się zapisać ustawień: {exc}")
            self.log(f"Raport błędu zapisano do: {log_path}")

    def destroy(self):
        try:
            if hasattr(self, "single_algo_var"):
                self._save_settings()
        finally:
            try:
                super().destroy()
            except tk.TclError:
                pass
