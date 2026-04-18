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

from .constants import APP_NAME, APP_VERSION, CONTAINER_EXT, DEFAULT_CHUNK, QUEUE_POLL_MS
from .container import read_container_header
from .jobs import compress_job, decompress_job, estimate_output, verify_archive_job
from .error_logging import write_error_report, write_exception_report
from .models import SourceSpec
from .paths import LOGS_DIR, SETTINGS_FILE
from .utils import ensure_dir, format_seconds, human_size, read_text_file
from .worker import Worker


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1180x860")
        self.minsize(1080, 760)

        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.current_worker: Optional[Worker] = None
        self.progress_start_time = 0.0
        self.last_output_file: Optional[Path] = None

        self._build_variables()
        ensure_dir(LOGS_DIR)
        self._build_ui()
        self._load_settings()
        self.log(f"Folder log?w b??d?w: {LOGS_DIR}")
        self.after(QUEUE_POLL_MS, self._poll_queue)

    def report_callback_exception(self, exc, val, tb):
        log_path = write_exception_report(
            exc,
            val,
            tb,
            context="Nieobs?u?ony wyj?tek w callbacku interfejsu Tkinter.",
        )
        self.status_var.set("B??d krytyczny interfejsu.")
        self.log(f"B??d krytyczny interfejsu. Raport zapisano do: {log_path}")
        messagebox.showerror(
            "B??d krytyczny",
            f"Wyst?pi? nieobs?u?ony b??d interfejsu.\n\nRaport zapisano do:\n{log_path}",
        )

    def _build_variables(self):
        self.file_path_var = tk.StringVar()
        self.decode_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.text_name_var = tk.StringVar(value="tekst_wejsciowy.txt")

        self.algo_mode_var = tk.StringVar(value="single")
        self.single_algo_var = tk.StringVar(value=AVAILABLE_ALGOS[0] if AVAILABLE_ALGOS else "")
        self.level_var = tk.IntVar(value=6)
        self.chunk_var = tk.StringVar(value="1 MB")

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
        right = ttk.Frame(main, padding=8)
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
        self._build_settings(right)
        self._build_status(right)
        self._build_log(right)

    def _build_tab_file(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Kodowanie pliku")

        ttk.Label(tab, text="Plik wejściowy:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.file_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(tab, text="Wybierz…", command=self.choose_file).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.file_info_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 4))
        ttk.Label(
            tab,
            text="Domyślnie wynik zapisze się obok pliku wejściowego, chyba że wskażesz katalog wyjściowy po prawej.",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_file).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Koduj plik", command=self.start_encode_file).pack(side="left")

    def _build_tab_text(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.notebook.add(tab, text="Kodowanie tekstu")

        row1 = ttk.Frame(tab)
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(1, weight=1)

        ttk.Label(row1, text="Nazwa tekstu / przyszłego pliku:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(row1, textvariable=self.text_name_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(row1, text="Wczytaj TXT…", command=self.load_text_from_file).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.text_info_var).grid(row=1, column=0, sticky="w", pady=(4, 4))

        self.text_box = tk.Text(tab, wrap="word", undo=True, font=("Consolas", 11))
        self.text_box.grid(row=2, column=0, sticky="nsew", pady=6)
        self.text_box.bind("<<Modified>>", self.on_text_modified)

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="Wyczyść", command=lambda: self.text_box.delete("1.0", "end")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_text).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Koduj tekst", command=self.start_encode_text).pack(side="left")

    def _build_tab_decode(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Dekodowanie")

        ttk.Label(tab, text="Archiwum *.pylc:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.decode_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(tab, text="Wybierz…", command=self.choose_archive).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.header_info_var, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 6))
        ttk.Label(
            tab,
            text="Jeśli zaznaczysz ‘Przywracaj do oryginalnej lokalizacji’, program spróbuje użyć ścieżki zapisanej w archiwum; w przeciwnym razie użyje katalogu wyjściowego lub folderu domyślnego.",
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Czytaj nagłówek", command=self.load_archive_header).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Test integralności", command=self.start_verify_archive).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Dekoduj", command=self.start_decode).pack(side="left")

    def _build_settings(self, parent):
        frm = ttk.LabelFrame(parent, text="Ustawienia", padding=10)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Katalog wyjściowy:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(frm, text="Wybierz…", command=self.choose_output_dir).grid(row=0, column=2, pady=4)

        ttk.Separator(frm, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(frm, text="Tryb kompresji:").grid(row=2, column=0, sticky="w", pady=4)
        row = ttk.Frame(frm)
        row.grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(row, text="Jeden algorytm", variable=self.algo_mode_var, value="single").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(row, text="Minimum z wybranych", variable=self.algo_mode_var, value="auto").pack(side="left")

        ttk.Label(frm, text="Algorytm:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(frm, state="readonly", values=AVAILABLE_ALGOS, textvariable=self.single_algo_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frm, text="Poziom:").grid(row=3, column=2, sticky="e", pady=4)
        ttk.Spinbox(frm, from_=0, to=9, textvariable=self.level_var, width=6).grid(row=3, column=2, sticky="w", padx=(54, 0), pady=4)

        ttk.Label(frm, text="Auto-test algorytmów:").grid(row=4, column=0, sticky="nw", pady=4)
        auto_box = ttk.Frame(frm)
        auto_box.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(auto_box, text="zlib", variable=self.auto_zlib_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="gzip", variable=self.auto_gzip_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="bz2", variable=self.auto_bz2_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="lzma", variable=self.auto_lzma_var).pack(side="left")

        ttk.Label(frm, text="Rozmiar porcji:").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(frm, state="readonly", values=["256 KB", "512 KB", "1 MB", "4 MB"], textvariable=self.chunk_var, width=12).grid(row=5, column=1, sticky="w", padx=6, pady=4)

        ttk.Checkbutton(frm, text="Nadpisuj istniejące pliki", variable=self.overwrite_var).grid(row=6, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Weryfikuj SHA-256 przy dekodowaniu", variable=self.verify_hash_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Przywracaj znacznik czasu pliku po dekodowaniu", variable=self.restore_mtime_var).grid(row=8, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Przywracaj do oryginalnej lokalizacji, jeśli istnieje", variable=self.prefer_original_path_var).grid(row=9, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Jeśli źródłem był tekst, po dekodowaniu załaduj go też do pola", variable=self.load_text_on_decode_var).grid(row=10, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Otwórz folder po zakończeniu", variable=self.open_folder_var).grid(row=11, column=0, columnspan=3, sticky="w", pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="Anuluj", command=self.cancel_current_job).pack(side="left")
        ttk.Button(btns, text="Otwórz ostatni folder", command=self.open_last_output_folder).pack(side="left", padx=(8, 0))

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

        self.log_box = tk.Text(frm, height=16, wrap="word", state="disabled", font=("Consolas", 10))
        self.log_box.grid(row=0, column=0, sticky="nsew")

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
                title="B??d wczytywania pliku tekstowego",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context=f"Nie uda?o si? wczyta? pliku tekstowego: {path}",
            )
            self.log(f"Nie uda?o si? wczyta? tekstu z pliku: {path}")
            self.log(f"Raport b??du zapisano do: {log_path}")
            messagebox.showerror(
                "B??d",
                f"Nie uda?o si? wczyta? tekstu z pliku:\n{exc}\n\nRaport zapisano do:\n{log_path}",
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
        self.text_info_var.set(f"Tekst: {char_count} znak?w / {human_size(byte_count)}")
        self.input_size_var.set(f"Wej?cie: {human_size(byte_count)}")

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
            messagebox.showerror("Błąd", str(e))
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
        self.status_var.set(f"B??d: {item['message']}")
        if item.get("traceback"):
            self.log(item["traceback"])
        log_path = write_error_report(
            title=f"B??d zadania: {item.get('task', 'nieznane')}",
            message=item["message"],
            traceback_text=item.get("traceback", ""),
            context="Wyj?tek przechwycony w w?tku roboczym i przekazany do GUI.",
            extra_lines=[f"Czas zadania: {item.get('elapsed', 0.0):.3f} s"],
        )
        self.log(f"Raport b??du zapisano do: {log_path}")
        messagebox.showerror(
            "B??d",
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
                title="B??d wczytywania ustawie?",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context="Wyj?tek podczas odczytu pliku ustawie? aplikacji.",
            )
            self.log(f"Nie uda?o si? wczyta? ustawie?: {exc}")
            self.log(f"Raport b??du zapisano do: {log_path}")

        self.update_file_info()
        self.on_text_modified()

    def _save_settings(self):
        data = {
            "output_dir": self.output_dir_var.get(),
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
                title="B??d zapisu ustawie?",
                message=str(exc),
                traceback_text=traceback.format_exc(),
                context="Wyj?tek podczas zapisu pliku ustawie? aplikacji.",
            )
            self.log(f"Nie uda?o si? zapisa? ustawie?: {exc}")
            self.log(f"Raport b??du zapisano do: {log_path}")

    def destroy(self):
        self._save_settings()
        super().destroy()
