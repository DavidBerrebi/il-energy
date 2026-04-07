"""EVERGREEN EnergyPlus Simulator — Desktop GUI.

Launch with:
    python -m il_energy.gui
or (after pip install):
    il-energy-gui
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import (
    END, LEFT, RIGHT, BOTH, X, Y, TOP, BOTTOM, HORIZONTAL, VERTICAL,
    StringVar, filedialog, messagebox, scrolledtext,
)
import tkinter as tk
import tkinter.ttk as ttk

# macOS-compatible Button that respects fg/bg colors
try:
    from tkmacosx import Button as _Button  # type: ignore
except ImportError:
    _Button = tk.Button  # fallback on non-macOS

# Optional PDF viewer
try:
    from tkinterweb import HtmlFrame  # type: ignore
    _HAS_TKWEB = True
except ImportError:
    _HAS_TKWEB = False


# ── Colours / fonts ───────────────────────────────────────────────────────────
_BG = "#ffffff"
_PANEL = "#f5f9f0"
_ACCENT = "#2d7a2d"
_ACCENT_HOVER = "#1f5e1f"
_BTN_SECONDARY = "#4a9a4a"
_BTN_OPEN = "#6b6b6b"
_TEXT = "#1a1a1a"
_TEXT_DIM = "#555555"
_ENTRY_BG = "#ffffff"
_LOG_BG = "#f0f4ec"
_LOG_FG = "#1a3a1a"
_BORDER = "#c0d8b0"
_FONT = ("Helvetica Neue", 10)
_FONT_BOLD = ("Helvetica Neue", 10, "bold")
_FONT_TITLE = ("Helvetica Neue", 15, "bold")
_FONT_SMALL = ("Helvetica Neue", 8)


def _open_path(path: Path) -> None:
    """Open a file in the system default viewer."""
    if platform.system() == "Darwin":
        subprocess.run(["open", str(path)])
    elif platform.system() == "Windows":
        os.startfile(str(path))
    else:
        subprocess.run(["xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("EVERGREEN EnergyPlus Simulator")
        self.configure(bg=_BG)
        self.minsize(900, 700)
        self.geometry("1100x820")

        self._pdf_paths: list[Path] = []
        self._viewer_idx: int = 0
        self._running = False

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Title bar
        title_frame = tk.Frame(self, bg=_ACCENT, pady=10)
        title_frame.pack(fill=X)
        tk.Label(
            title_frame, text="EVERGREEN EnergyPlus Simulator",
            font=_FONT_TITLE, fg="white", bg=_ACCENT,
        ).pack(side=LEFT, padx=20)

        # ── Input section ─────────────────────────────────────────────────────
        input_frame = tk.LabelFrame(
            self, text="Inputs", font=_FONT_BOLD,
            fg=_TEXT, bg=_PANEL, bd=1, padx=12, pady=8,
        )
        input_frame.pack(fill=X, padx=20, pady=(0, 8))

        self._idf_var = StringVar()
        self._epw_var = StringVar()
        self._out_var = StringVar()

        self._make_file_row(input_frame, "IDF File:", self._idf_var, 0, mode="idf")
        self._make_file_row(input_frame, "EPW File:", self._epw_var, 1, mode="epw")
        self._make_file_row(input_frame, "Output Dir:", self._out_var, 2, mode="dir")

        # EnergyPlus version dropdown
        opts_frame = tk.Frame(input_frame, bg=_PANEL)
        opts_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        tk.Label(opts_frame, text="EnergyPlus Version:", font=_FONT, fg=_TEXT, bg=_PANEL).pack(side=LEFT)
        self._ep_ver_var = StringVar(value="25")
        ep_ver_cb = ttk.Combobox(
            opts_frame, textvariable=self._ep_ver_var,
            values=["25"], state="readonly", width=6, font=_FONT,
        )
        ep_ver_cb.pack(side=LEFT, padx=(6, 0))

        input_frame.columnconfigure(1, weight=1)

        # ── RUN button ────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=_BG)
        btn_frame.pack(pady=6)

        self._run_btn = _Button(
            btn_frame, text="  RUN  ", font=("Helvetica Neue", 12, "bold"),
            bg=_ACCENT, fg="white", activebackground=_ACCENT_HOVER,
            activeforeground="white", relief="flat", padx=20, pady=8,
            cursor="hand2", command=self._on_run,
        )
        self._run_btn.pack()

        # ── Main paned area (log top, results bottom) ─────────────────────────
        paned = ttk.PanedWindow(self, orient=VERTICAL)
        paned.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        # Log panel
        log_frame = tk.LabelFrame(
            paned, text="Log", font=_FONT_BOLD,
            fg=_TEXT, bg=_PANEL, bd=1,
        )
        paned.add(log_frame, weight=1)

        self._log = scrolledtext.ScrolledText(
            log_frame, font=("Courier", 8), bg=_LOG_BG, fg=_LOG_FG,
            insertbackground=_TEXT, relief="flat", wrap="word",
        )
        self._log.pack(fill=BOTH, expand=True, padx=4, pady=4)
        self._log.configure(state="disabled")

        # Results panel — left: PDF list, right: viewer
        results_frame = tk.LabelFrame(
            paned, text="Output PDFs", font=_FONT_BOLD,
            fg=_TEXT, bg=_PANEL, bd=1,
        )
        paned.add(results_frame, weight=2)

        results_paned = ttk.PanedWindow(results_frame, orient=HORIZONTAL)
        results_paned.pack(fill=BOTH, expand=True, padx=4, pady=4)

        # PDF list (scrollable)
        list_outer = tk.Frame(results_paned, bg=_PANEL)
        results_paned.add(list_outer, weight=1)

        list_scroll = tk.Scrollbar(list_outer, orient=VERTICAL)
        list_scroll.pack(side=RIGHT, fill=Y)

        self._pdf_canvas = tk.Canvas(list_outer, bg=_PANEL, highlightthickness=0,
                                     yscrollcommand=list_scroll.set)
        self._pdf_canvas.pack(fill=BOTH, expand=True)
        list_scroll.config(command=self._pdf_canvas.yview)

        self._pdf_list_frame = tk.Frame(self._pdf_canvas, bg=_PANEL)
        self._pdf_canvas_window = self._pdf_canvas.create_window(
            (0, 0), window=self._pdf_list_frame, anchor="nw"
        )
        self._pdf_list_frame.bind(
            "<Configure>",
            lambda e: self._pdf_canvas.configure(
                scrollregion=self._pdf_canvas.bbox("all")
            ),
        )
        self._pdf_canvas.bind(
            "<Configure>",
            lambda e: self._pdf_canvas.itemconfig(
                self._pdf_canvas_window, width=e.width
            ),
        )

        # PDF viewer (right side)
        viewer_outer = tk.Frame(results_paned, bg=_PANEL)
        results_paned.add(viewer_outer, weight=3)

        # Viewer nav bar
        nav_bar = tk.Frame(viewer_outer, bg=_PANEL)
        nav_bar.pack(fill=X, pady=(0, 4))

        self._prev_btn = _Button(
            nav_bar, text="◀ Prev", font=_FONT, bg=_ACCENT, fg="white",
            relief="flat", padx=8, cursor="hand2",
            command=self._viewer_prev,
        )
        self._prev_btn.pack(side=LEFT, padx=(0, 4))

        self._viewer_label = tk.Label(
            nav_bar, text="— no PDF selected —", font=_FONT_SMALL,
            fg=_TEXT_DIM, bg=_PANEL,
        )
        self._viewer_label.pack(side=LEFT, expand=True)

        self._next_btn = _Button(
            nav_bar, text="Next ▶", font=_FONT, bg=_ACCENT, fg="white",
            relief="flat", padx=8, cursor="hand2",
            command=self._viewer_next,
        )
        self._next_btn.pack(side=RIGHT, padx=(4, 0))

        # Viewer widget
        self._viewer_container = tk.Frame(viewer_outer, bg=_PANEL)
        self._viewer_container.pack(fill=BOTH, expand=True)

        if _HAS_TKWEB:
            self._html_frame = HtmlFrame(self._viewer_container, messages_enabled=False)
            self._html_frame.pack(fill=BOTH, expand=True)
        else:
            tk.Label(
                self._viewer_container,
                text=(
                    "Inline PDF viewer not available.\n"
                    "Install tkinterweb:  pip install tkinterweb\n\n"
                    "Use the [Open] buttons to view PDFs in your system viewer."
                ),
                font=_FONT, fg=_TEXT_DIM, bg=_PANEL, justify="center",
            ).pack(expand=True)

    def _make_file_row(
        self, parent: tk.Frame, label: str, var: StringVar, row: int, mode: str
    ) -> None:
        tk.Label(parent, text=label, font=_FONT, fg=_TEXT, bg=_PANEL, width=12,
                 anchor="e").grid(row=row, column=0, sticky="e", pady=3, padx=(0, 6))

        entry = tk.Entry(parent, textvariable=var, font=_FONT, bg=_ENTRY_BG,
                         fg=_TEXT, insertbackground=_TEXT, relief="solid", bd=1,
                         highlightcolor=_ACCENT, highlightthickness=1)
        entry.grid(row=row, column=1, sticky="ew", pady=3)

        def browse(m=mode, v=var):
            if m == "idf":
                p = filedialog.askopenfilename(
                    title="Select IDF file",
                    filetypes=[("IDF files", "*.idf"), ("All files", "*.*")],
                )
            elif m == "epw":
                p = filedialog.askopenfilename(
                    title="Select EPW weather file",
                    filetypes=[("EPW files", "*.epw"), ("All files", "*.*")],
                )
            else:
                p = filedialog.askdirectory(title="Select output directory")
            if p:
                v.set(p)

        _Button(
            parent, text="Browse", font=_FONT, bg=_ACCENT, fg="white",
            activebackground=_ACCENT_HOVER, activeforeground="white",
            relief="flat", padx=8, cursor="hand2", command=browse,
        ).grid(row=row, column=2, padx=(6, 0), pady=3)

    # ── Run logic ─────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        idf = self._idf_var.get().strip()
        epw = self._epw_var.get().strip()
        out = self._out_var.get().strip()

        if not idf or not Path(idf).is_file():
            messagebox.showerror("Input Error", "Please select a valid IDF file.")
            return
        if not epw or not Path(epw).is_file():
            messagebox.showerror("Input Error", "Please select a valid EPW file.")
            return
        if not out:
            messagebox.showerror("Input Error", "Please select an output directory.")
            return

        self._run_btn.configure(state="disabled", bg="#999")
        self._clear_log()
        self._clear_pdf_list()
        self._running = True

        thread = threading.Thread(
            target=self._run_simulation,
            args=(idf, epw, out),
            daemon=True,
        )
        thread.start()

    def _run_simulation(self, idf: str, epw: str, out: str) -> None:
        cmd = [
            sys.executable, "-m", "il_energy", "run",
            "--idf", idf,
            "--epw", epw,
            "--output-dir", out,
        ]
        self._log_append(f"$ {' '.join(cmd)}\n\n")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:  # type: ignore[union-attr]
                self._log_append(line)
            proc.wait()
            status = "✓ Simulation complete." if proc.returncode == 0 else f"✗ Exit code {proc.returncode}"
            self._log_append(f"\n{status}\n")
        except Exception as exc:
            self._log_append(f"\nError: {exc}\n")

        self.after(0, lambda: self._on_run_complete(out))

    def _on_run_complete(self, out_dir: str) -> None:
        self._running = False
        self._run_btn.configure(state="normal", bg=_ACCENT)
        self._populate_pdf_list(Path(out_dir))

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log_append(self, text: str) -> None:
        def _do():
            self._log.configure(state="normal")
            self._log.insert(END, text)
            self._log.see(END)
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", END)
        self._log.configure(state="disabled")

    # ── PDF list ──────────────────────────────────────────────────────────────

    def _clear_pdf_list(self) -> None:
        for w in self._pdf_list_frame.winfo_children():
            w.destroy()
        self._pdf_paths = []
        self._viewer_idx = 0
        self._viewer_label.configure(text="— no PDF selected —")
        if _HAS_TKWEB:
            self._html_frame.load_html("")

    def _populate_pdf_list(self, out_dir: Path) -> None:
        self._clear_pdf_list()

        # Gather PDFs: top-level first, then full/
        pdfs: list[Path] = []
        for p in sorted(out_dir.glob("*.pdf")):
            pdfs.append(p)
        full_dir = out_dir / "full"
        if full_dir.is_dir():
            for p in sorted(full_dir.glob("*.pdf")):
                pdfs.append(p)

        self._pdf_paths = pdfs

        if not pdfs:
            tk.Label(
                self._pdf_list_frame, text="No PDF outputs found.",
                font=_FONT_SMALL, fg=_TEXT_DIM, bg=_PANEL,
            ).pack(anchor="w", padx=8, pady=4)
            return

        for i, pdf in enumerate(pdfs):
            row = tk.Frame(self._pdf_list_frame, bg=_PANEL)
            row.pack(fill=X, padx=4, pady=1)

            display_name = (
                f"full/{pdf.name}" if pdf.parent.name == "full" else pdf.name
            )
            tk.Label(
                row, text=display_name, font=_FONT_SMALL, fg=_TEXT, bg=_PANEL,
                anchor="w", width=30,
            ).pack(side=LEFT, fill=X, expand=True)

            idx = i  # capture for lambda
            _Button(
                row, text="View", font=_FONT_SMALL, bg=_ACCENT, fg="white",
                relief="flat", padx=4, cursor="hand2",
                command=lambda i=idx: self._viewer_show(i),
            ).pack(side=LEFT, padx=(2, 1))

            _Button(
                row, text="Open", font=_FONT_SMALL, bg=_BTN_OPEN, fg="white",
                relief="flat", padx=4, cursor="hand2",
                command=lambda p=pdf: _open_path(p),
            ).pack(side=LEFT, padx=(1, 2))

        # Auto-show first PDF
        self._viewer_show(0)

    # ── PDF viewer ────────────────────────────────────────────────────────────

    def _viewer_show(self, idx: int) -> None:
        if not self._pdf_paths:
            return
        idx = max(0, min(idx, len(self._pdf_paths) - 1))
        self._viewer_idx = idx
        pdf = self._pdf_paths[idx]

        label = (
            f"full/{pdf.name}" if pdf.parent.name == "full" else pdf.name
        )
        self._viewer_label.configure(
            text=f"{label}  ({idx + 1} / {len(self._pdf_paths)})"
        )

        if _HAS_TKWEB:
            uri = pdf.as_uri()
            html = (
                f"<html><body style='margin:0;padding:0;background:#f0f4ec'>"
                f"<embed src='{uri}' width='100%' height='100%' "
                f"type='application/pdf'>"
                f"</body></html>"
            )
            self._html_frame.load_html(html)

    def _viewer_prev(self) -> None:
        self._viewer_show(self._viewer_idx - 1)

    def _viewer_next(self) -> None:
        self._viewer_show(self._viewer_idx + 1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
