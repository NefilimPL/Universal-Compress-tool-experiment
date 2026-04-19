from __future__ import annotations

import tkinter as tk


class ToolTip:
    def __init__(self, widget, text: str, *, delay_ms: int = 450, wraplength: int = 320):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self._after_id = None
        self._window = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")
        self.widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, _event=None):
        self._cancel_schedule()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _on_leave(self, _event=None):
        self._cancel_schedule()
        self._hide()

    def _on_destroy(self, _event=None):
        self._cancel_schedule()
        self._hide()

    def _cancel_schedule(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._window is not None or not self.text:
            return

        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        try:
            self._window.attributes("-topmost", True)
        except tk.TclError:
            pass

        x = self.widget.winfo_pointerx() + 14
        y = self.widget.winfo_pointery() + 18
        self._window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            self._window,
            text=self.text,
            justify="left",
            anchor="w",
            padx=8,
            pady=6,
            background="#fff7d6",
            foreground="#202020",
            relief="solid",
            borderwidth=1,
            wraplength=self.wraplength,
            font=("Segoe UI", 9),
        )
        label.pack()

    def _hide(self):
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None
