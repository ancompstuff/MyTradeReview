from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config


def _load_last_selection() -> dict:
    if not config.SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_last_selection(data: dict) -> None:
    try:
        config.SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Non-fatal: picker still works even if persistence fails.
        pass


def ask_for_files(parent) -> tuple[Path, str, Path] | None:
    """
    Open a modal dialog to choose:
      - trades CSV
      - market type: WINFUT / WDOFUT / BOVESPA
      - market data CSV

    Returns:
      (trades_file, market_choice, market_file) or None when cancelled.
    """
    last = _load_last_selection()

    top = tk.Toplevel(parent)
    top.title("Select input files")
    top.resizable(False, False)
    top.transient(parent)
    top.grab_set()

    frame = ttk.Frame(top, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    trades_var = tk.StringVar(value=last.get("trades_file", str(config.DEFAULT_TRADES_FILE)))
    market_choice_var = tk.StringVar(value=last.get("market_choice", config.DEFAULT_MARKET_CHOICE))
    market_file_var = tk.StringVar(value=last.get("market_file", str(config.DEFAULT_MARKET_FILES[config.DEFAULT_MARKET_CHOICE])))

    def _initial_dir(path_str: str, fallback_dir: Path) -> str:
        p = Path(path_str) if path_str else fallback_dir
        if p.is_file():
            return str(p.parent)
        if p.exists() and p.is_dir():
            return str(p)
        return str(fallback_dir)

    def choose_trades():
        selected = filedialog.askopenfilename(
            parent=top,
            title="What trade file to use?",
            initialdir=_initial_dir(trades_var.get(), config.DEFAULT_TRADES_DIR),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected:
            trades_var.set(selected)

    def choose_market_file():
        selected = filedialog.askopenfilename(
            parent=top,
            title=f"Select data CSV for {market_choice_var.get()}",
            initialdir=_initial_dir(market_file_var.get(), config.DEFAULT_MARKET_DIR),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected:
            market_file_var.set(selected)

    def on_market_choice_changed(*_args):
        # If current path is empty/non-file, preload default for selected market.
        current = Path(market_file_var.get()) if market_file_var.get() else None
        if current is None or not current.exists():
            market_file_var.set(str(config.DEFAULT_MARKET_FILES[market_choice_var.get()]))

    market_choice_var.trace_add("write", on_market_choice_changed)

    ttk.Label(frame, text="Trades CSV:").grid(row=0, column=0, sticky="w", pady=(0, 6))
    ttk.Entry(frame, textvariable=trades_var, width=72).grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=(0, 6))
    ttk.Button(frame, text="Browse...", command=choose_trades).grid(row=0, column=2, sticky="e", pady=(0, 6))

    ttk.Label(frame, text="Market type:").grid(row=1, column=0, sticky="w", pady=(0, 6))
    ttk.Combobox(
        frame,
        textvariable=market_choice_var,
        values=config.MARKET_CHOICES,
        state="readonly",
        width=18,
    ).grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(0, 6))

    ttk.Label(frame, text="Market CSV:").grid(row=2, column=0, sticky="w")
    ttk.Entry(frame, textvariable=market_file_var, width=72).grid(row=2, column=1, sticky="ew", padx=(8, 8))
    ttk.Button(frame, text="Browse...", command=choose_market_file).grid(row=2, column=2, sticky="e")

    frame.columnconfigure(1, weight=1)

    result = {"value": None}

    def on_ok():
        trades = Path(trades_var.get()).expanduser()
        market_file = Path(market_file_var.get()).expanduser()
        market_choice = market_choice_var.get()

        if market_choice not in config.MARKET_CHOICES:
            messagebox.showerror("Invalid market", "Please choose WINFUT, WDOFUT, or BOVESPA.", parent=top)
            return
        if not trades.exists() or not trades.is_file():
            messagebox.showerror("Trades file missing", f"Trades file not found:\n{trades}", parent=top)
            return
        if not market_file.exists() or not market_file.is_file():
            messagebox.showerror("Market file missing", f"Market data file not found:\n{market_file}", parent=top)
            return

        _save_last_selection(
            {
                "trades_file": str(trades),
                "market_choice": market_choice,
                "market_file": str(market_file),
            }
        )
        result["value"] = (trades, market_choice, market_file)
        top.destroy()

    def on_cancel():
        top.destroy()

    btns = ttk.Frame(frame)
    btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)
    ttk.Button(btns, text="Load", command=on_ok).pack(side=tk.RIGHT, padx=(0, 6))

    top.bind("<Return>", lambda _e: on_ok())
    top.bind("<Escape>", lambda _e: on_cancel())

    parent.wait_window(top)
    return result["value"]