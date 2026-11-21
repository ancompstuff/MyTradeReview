"""Present file-selection dialogs and remember the user's previous trades and market inputs."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config


def _load_last() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_last(data: dict) -> None:
    try:
        config.SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def ask_for_files(parent):
    """
    Returns (trades_file, market_choice, data_file, source) or None.
    source = "minute" (Profit 1-minute CSV) or "tick" (Scalper Pro tick CSV).
    """
    last = _load_last()
    top = tk.Toplevel(parent)
    top.title("Select input files")
    top.resizable(False, False)
    top.transient(parent)
    top.grab_set()
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    choice0 = last.get("market_choice", config.DEFAULT_MARKET_CHOICE)
    reviews_var = tk.StringVar(value=last.get("reviews_file", str(config.REVIEWS_FILE)))
    trades_var = tk.StringVar(value=last.get("trades_file", str(config.DEFAULT_TRADES_FILE)))
    market_var = tk.StringVar(value=choice0)
    source_var = tk.StringVar(value=last.get("source", "minute"))
    minute_var = tk.StringVar(value=last.get("market_file", str(config.DEFAULT_MARKET_FILES[choice0])))
    tick_var = tk.StringVar(value=last.get("tick_file", ""))
    pdf_output_var = tk.StringVar(value=last.get("pdf_output_dir", str(config.OUTPUT_DIR)))

    def start_dir(value: str, fallback: Path) -> str:
        p = Path(value) if value else fallback
        if p.is_file():
            return str(p.parent)
        return str(p) if p.is_dir() else str(fallback)

    def browse(var, title, fallback):
        f = filedialog.askopenfilename(
            parent=top, title=title, initialdir=start_dir(var.get(), fallback),
            filetypes=[("CSV / text", "*.csv *.txt"), ("All files", "*.*")])
        if f:
            var.set(f)

    ttk.Label(frame, text="Trades CSV:").grid(row=0, column=0, sticky="w", pady=(0, 6))
    ttk.Entry(frame, textvariable=trades_var, width=72).grid(row=0, column=1, padx=8, pady=(0, 6))
    ttk.Button(frame, text="Browse...", command=lambda: browse(
        trades_var, "What trade file to use?", config.DEFAULT_TRADES_DIR)).grid(row=0, column=2, pady=(0, 6))

    ttk.Label(frame, text="Market type:").grid(row=1, column=0, sticky="w", pady=(0, 6))
    ttk.Combobox(frame, textvariable=market_var, values=config.MARKET_CHOICES,
                 state="readonly", width=18).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 6))

    ttk.Label(frame, text="Data source:").grid(row=2, column=0, sticky="w", pady=(0, 6))
    src = ttk.Frame(frame)
    src.grid(row=2, column=1, sticky="w", padx=8, pady=(0, 6))
    ttk.Radiobutton(src, text="1-minute CSV (Profit)", variable=source_var, value="minute").pack(side=tk.LEFT)
    ttk.Radiobutton(src, text="Tick CSV (Scalper Pro, day trade)", variable=source_var,
                    value="tick").pack(side=tk.LEFT, padx=(16, 0))

    ttk.Label(frame, text="1-minute CSV:").grid(row=3, column=0, sticky="w", pady=(0, 6))
    minute_entry = ttk.Entry(frame, textvariable=minute_var, width=72)
    minute_entry.grid(row=3, column=1, padx=8, pady=(0, 6))
    minute_btn = ttk.Button(frame, text="Browse...", command=lambda: browse(
        minute_var, f"Select 1-minute CSV for {market_var.get()}", config.DEFAULT_MARKET_DIR))
    minute_btn.grid(row=3, column=2, pady=(0, 6))

    ttk.Label(frame, text="Tick CSV:").grid(row=4, column=0, sticky="w")
    tick_entry = ttk.Entry(frame, textvariable=tick_var, width=72)
    tick_entry.grid(row=4, column=1, padx=8)
    tick_btn = ttk.Button(frame, text="Browse...", command=lambda: browse(
        tick_var, "Select tick file (Scalper Pro)", config.DEFAULT_MARKET_DIR))
    tick_btn.grid(row=4, column=2)

    ttk.Label(frame, text="Trade reviews CSV:").grid(row=5, column=0, sticky="w", pady=(8, 0))
    ttk.Entry(frame, textvariable=reviews_var, width=72).grid(row=5, column=1, padx=8, pady=(8, 0))

    def browse_reviews():
        initial = Path(reviews_var.get()).expanduser()
        initial_dir = str(initial.parent if initial.suffix else initial)
        f = filedialog.asksaveasfilename(
            parent=top,
            title="Select trade reviews CSV location",
            initialdir=initial_dir,
            initialfile=initial.name if initial.name else "trade_reviews.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if f:
            reviews_var.set(f)

    ttk.Button(frame, text="Browse...", command=browse_reviews).grid(row=5, column=2, pady=(8, 0))

    def toggle(*_a):
        tick = source_var.get() == "tick"
        for w in (minute_entry, minute_btn):
            w.state(["disabled"] if tick else ["!disabled"])
        for w in (tick_entry, tick_btn):
            w.state(["!disabled"] if tick else ["disabled"])

    source_var.trace_add("write", toggle)
    toggle()

    def on_market_change(*_a):
        p = Path(minute_var.get()) if minute_var.get() else None
        if p is None or not p.exists():
            minute_var.set(str(config.DEFAULT_MARKET_FILES[market_var.get()]))

    market_var.trace_add("write", on_market_change)

    ttk.Label(frame, text="PDF output folder:").grid(row=6, column=0, sticky="w", pady=(8, 0))
    ttk.Entry(frame, textvariable=pdf_output_var, width=72, state="readonly").grid(row=6, column=1, padx=8, pady=(8, 0))

    result = {"value": None}

    def on_ok():
        trades = Path(trades_var.get()).expanduser()
        source = source_var.get()
        data = Path((tick_var if source == "tick" else minute_var).get()).expanduser()
        if not trades.is_file():
            messagebox.showerror("Trades file missing", f"Not found:\n{trades}", parent=top)
            return
        if not data.is_file():
            messagebox.showerror("Data file missing", f"Not found:\n{data}", parent=top)
            return
        reviews_file = Path(reviews_var.get()).expanduser()
        if reviews_file.suffix.lower() != ".csv":
            messagebox.showerror("Invalid reviews file", "Trade reviews file must end with .csv", parent=top)
            return
        _save_last({
            "trades_file": str(trades), "market_choice": market_var.get(), "source": source,
            "market_file": minute_var.get(), "tick_file": tick_var.get(),
            "reviews_file": str(reviews_file),
        })
        result["value"] = (trades, market_var.get(), data, source, reviews_file)
        top.destroy()

    btns = ttk.Frame(frame)
    btns.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Cancel", command=top.destroy).pack(side=tk.RIGHT)
    ttk.Button(btns, text="Load", command=on_ok).pack(side=tk.RIGHT, padx=(0, 6))
    top.bind("<Return>", lambda _e: on_ok())
    top.bind("<Escape>", lambda _e: top.destroy())

    parent.wait_window(top)
    return result["value"]