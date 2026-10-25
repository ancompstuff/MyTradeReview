from __future__ import annotations

import warnings

# Keep PyCharm's Run console useful. These are known pandas transition warnings,
# not runtime errors in this application. Real exceptions are NOT hidden.
warnings.filterwarnings(
    "ignore",
    message=r".*Pyarrow will become a required dependency of pandas.*",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*ChainedAssignmentError: behaviour will change in pandas 3\.0!.*",
    category=FutureWarning,
)

import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd

import config
from data_loader import load_all
from charting import open_trade_chart
from reviews import load_reviews, save_review, merge_reviews
from stats import make_stats_report
from file_picker import ask_for_files


class TradeReviewApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("My Trade Review - 2026")
        self.geometry("1500x900")
        self.minsize(1150, 700)

        self.trades = pd.DataFrame()
        self.markets = {}
        self.reviews = pd.DataFrame()
        self.view_df = pd.DataFrame()
        self.selected_trade_id = None
        self.current_market_choice = None
        self.current_trades_file = None
        self.current_market_file = None

        self._build_ui()
        self.after(100, self.load_data)

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        self.summary_var = tk.StringVar(value="Loading data...")
        ttk.Label(top, textvariable=self.summary_var, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Button(top, text="Reload files", command=self.load_data).pack(side=tk.RIGHT, padx=3)
        ttk.Button(top, text="Show stats", command=self.show_stats).pack(side=tk.RIGHT, padx=3)
        ttk.Button(top, text="Open selected chart", command=self.open_selected_chart).pack(side=tk.RIGHT, padx=3)

        filters = ttk.Frame(self, padding=(8, 2, 8, 8))
        filters.pack(fill=tk.X)
        ttk.Label(filters, text="Instrument:").pack(side=tk.LEFT)
        self.instrument_var = tk.StringVar(value="All")
        self.instrument_combo = ttk.Combobox(filters, textvariable=self.instrument_var, values=["All"], width=12, state="readonly")
        self.instrument_combo.pack(side=tk.LEFT, padx=(4, 14))
        self.instrument_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        ttk.Label(filters, text="Outcome:").pack(side=tk.LEFT)
        self.outcome_var = tk.StringVar(value="All")
        out = ttk.Combobox(filters, textvariable=self.outcome_var, values=["All", "Win", "Loss", "Flat"], width=8, state="readonly")
        out.pack(side=tk.LEFT, padx=(4, 14))
        out.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        ttk.Label(filters, text="Review:").pack(side=tk.LEFT)
        self.review_filter_var = tk.StringVar(value="All")
        rev = ttk.Combobox(filters, textvariable=self.review_filter_var,
                           values=["All", "Unreviewed", "Reviewed"], width=11, state="readonly")
        rev.pack(side=tk.LEFT, padx=(4, 14))
        rev.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        ttk.Label(filters, text="Tip: single-click to select/review; double-click to open the chart.").pack(side=tk.LEFT, padx=15)

        table_frame = ttk.Frame(self, padding=(8, 0, 8, 5))
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ["Date", "Time", "Instrument", "Side", "Qty", "Entry", "Exit", "Duration", "PL", "DayPL", "NoDay", "Gap", "Process", "Tag"]
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        widths = {
            "Date": 90, "Time": 80, "Instrument": 85, "Side": 65, "Qty": 45,
            "Entry": 85, "Exit": 85, "Duration": 78, "PL": 80, "DayPL": 85,
            "NoDay": 60, "Gap": 78, "Process": 120, "Tag": 180,
        }
        headings = {
            "Date": "Date", "Time": "Entry time", "Instrument": "Contract", "Side": "Side", "Qty": "Qty",
            "Entry": "Entry", "Exit": "Exit", "Duration": "Hold", "PL": "P/L R$", "DayPL": "Day P/L after",
            "NoDay": "Trade #", "Gap": "Gap prev", "Process": "Process", "Tag": "Primary tag",
        }
        for c in columns:
            self.tree.heading(c, text=headings[c], command=lambda col=c: self.sort_tree(col, False))
            self.tree.column(c, width=widths[c], anchor=tk.CENTER if c not in ("Process", "Tag") else tk.W)

        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("Win", background="#eef9ee")
        self.tree.tag_configure("Loss", background="#fff0f0")
        self.tree.tag_configure("Flat", background="#f7f7f7")
        self.tree.bind("<<TreeviewSelect>>", self.on_select_trade)
        self.tree.bind("<Double-1>", lambda e: self.open_selected_chart())

        review = ttk.LabelFrame(self, text="Process review for selected trade", padding=8)
        review.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(review, text="Grade:").grid(row=0, column=0, sticky="w")
        self.grade_var = tk.StringVar(value="Unreviewed")
        ttk.Combobox(review, textvariable=self.grade_var, values=config.PROCESS_GRADES, state="readonly", width=22).grid(row=0, column=1, sticky="w", padx=(4, 14))

        ttk.Label(review, text="Setup:").grid(row=0, column=2, sticky="w")
        self.setup_var = tk.StringVar()
        ttk.Entry(review, textvariable=self.setup_var, width=24).grid(row=0, column=3, sticky="ew", padx=(4, 14))

        ttk.Label(review, text="Primary tag:").grid(row=0, column=4, sticky="w")
        self.tag_var = tk.StringVar()
        ttk.Combobox(review, textvariable=self.tag_var, values=config.MISTAKE_TAGS, width=29, state="readonly").grid(row=0, column=5, sticky="w", padx=(4, 14))

        ttk.Button(review, text="Save review", command=self.save_current_review).grid(row=0, column=6, padx=4)

        ttk.Label(review, text="Notes:").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.notes = tk.Text(review, height=3, wrap="word", font=("Segoe UI", 9))
        self.notes.grid(row=1, column=1, columnspan=6, sticky="ew", padx=(4, 0), pady=(8, 0))
        review.columnconfigure(3, weight=1)
        review.columnconfigure(6, weight=0)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def _refresh_instrument_filter_values(self):
        roots = sorted(self.trades["Root"].dropna().astype(str).unique().tolist()) if not self.trades.empty else []
        values = ["All"] + roots
        self.instrument_combo.configure(values=values)
        if self.instrument_var.get() not in values:
            self.instrument_var.set("All")

    def load_data(self):
        choice = ask_for_files(self)
        if choice is None:
            self.status_var.set("Load cancelled.")
            return

        trades_file, market_choice, market_file = choice
        self.current_trades_file = trades_file
        self.current_market_choice = market_choice
        self.current_market_file = market_file

        try:
            self.status_var.set("Reading selected trade and market files...")
            self.update_idletasks()
            trades, markets = load_all(trades_file, market_choice, market_file, config.MA_FAST, config.MA_SLOW)
            self.markets = markets
            self.reviews = load_reviews(config.REVIEWS_FILE)
            self.trades = merge_reviews(trades, self.reviews)
            self._refresh_instrument_filter_values()
            self.apply_filters()
            self.update_summary()

            root = next(iter(markets.keys()))
            self.status_var.set(
                f"Loaded {len(self.trades)} trades | {market_choice} bars: {len(markets[root]):,} | "
                f"Trades: {trades_file.name} | Data: {market_file.name} | Reviews: {config.REVIEWS_FILE.name}"
            )
        except Exception as exc:
            messagebox.showerror("Could not load files", f"{exc}")
            self.status_var.set("Load failed.")

    def update_summary(self):
        df = self.trades
        if df.empty:
            self.summary_var.set("No trades loaded")
            return
        wins = (df.PL > 0).sum()
        losses = (df.PL < 0).sum()
        avg_win = df.loc[df.PL > 0, "PL"].mean()
        avg_loss = df.loc[df.PL < 0, "PL"].mean()
        gross_win = df.loc[df.PL > 0, "PL"].sum()
        gross_loss = -df.loc[df.PL < 0, "PL"].sum()
        pf = gross_win / gross_loss if gross_loss > 0 else float("nan")
        self.summary_var.set(
            f"{len(df)} trades | Net R$ {df.PL.sum():.2f} | Win rate {wins/len(df):.1%} | "
            f"Avg win R$ {avg_win:.2f} | Avg loss R$ {avg_loss:.2f} | PF {pf:.2f} | {df.Date.nunique()} trading days"
        )

    def apply_filters(self):
        if self.trades.empty:
            self.view_df = self.trades.copy()
            self.populate_tree()
            return
        df = self.trades.copy()
        if self.instrument_var.get() != "All":
            df = df[df.Root == self.instrument_var.get()]
        if self.outcome_var.get() != "All":
            df = df[df.Outcome == self.outcome_var.get()]
        rf = self.review_filter_var.get()
        if rf == "Unreviewed":
            df = df[df.process_grade.eq("Unreviewed")]
        elif rf == "Reviewed":
            df = df[~df.process_grade.eq("Unreviewed")]
        self.view_df = df.copy()
        self.populate_tree()

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for _, r in self.view_df.iterrows():
            # WIN usually integer points; others decimal.
            if r.Root == "WIN":
                entry_fmt = f"{r.EntryPrice:,.0f}"
                exit_fmt = f"{r.ExitPrice:,.0f}"
            else:
                entry_fmt = f"{r.EntryPrice:,.1f}"
                exit_fmt = f"{r.ExitPrice:,.1f}"

            process_short = r.process_grade.replace(" - ", " ")
            vals = (
                r.EntryDT.strftime("%d/%m/%Y"), r.EntryDT.strftime("%H:%M:%S"), r.Ativo, r.Side,
                f"{r.Qty:.0f}", entry_fmt, exit_fmt, r.Duration, f"{r.PL:.2f}", f"{r.DayPLAfter:.2f}",
                f"{int(r.TradeNoDay)}/{int(r.TradesDay)}", r.GapPrev, process_short, r.mistake_tag,
            )
            self.tree.insert("", tk.END, iid=r.trade_id, values=vals, tags=(r.Outcome,))

    def selected_trade(self):
        sel = self.tree.selection()
        if not sel:
            return None
        tid = sel[0]
        rows = self.trades[self.trades.trade_id == tid]
        return None if rows.empty else rows.iloc[0]

    def on_select_trade(self, _event=None):
        trade = self.selected_trade()
        if trade is None:
            return
        self.selected_trade_id = trade.trade_id
        self.grade_var.set(trade.process_grade or "Unreviewed")
        self.setup_var.set(trade.setup or "")
        self.tag_var.set(trade.mistake_tag or "")
        self.notes.delete("1.0", tk.END)
        self.notes.insert("1.0", trade.notes or "")
        self.status_var.set(
            f"Selected {trade.Ativo} {trade.EntryDT:%d/%m/%Y %H:%M:%S} | {trade.Side} | P/L R$ {trade.PL:.2f} | Double-click or use Open selected chart."
        )

    def _chart_trade_ids_in_current_order(self):
        """Return trade IDs exactly as they are currently displayed in the table."""
        return list(self.tree.get_children(""))

    def _navigate_chart(self, current_trade_id, direction, chart_window):
        """Move to previous/next trade in the CURRENT visible/sorted table."""
        ids = self._chart_trade_ids_in_current_order()
        if current_trade_id not in ids:
            return
        current = ids.index(current_trade_id)
        target = current + direction
        if target < 0 or target >= len(ids):
            return

        next_id = ids[target]
        # Keep the main table synchronized with the chart being reviewed.
        self.tree.selection_set(next_id)
        self.tree.focus(next_id)
        self.tree.see(next_id)
        self.on_select_trade()

        if chart_window is not None and chart_window.winfo_exists():
            chart_window.destroy()
        self.open_selected_chart()

    def open_selected_chart(self):
        trade = self.selected_trade()
        if trade is None:
            messagebox.showinfo("Select a trade", "Select a trade in the table first.")
            return
        market = self.markets.get(trade.Root)
        if market is None:
            messagebox.showerror("No data", f"No market data loaded for {trade.Root}.")
            return

        ids = self._chart_trade_ids_in_current_order()
        try:
            pos = ids.index(trade.trade_id)
        except ValueError:
            pos = 0
        total = len(ids)

        open_trade_chart(
            self, market, trade,
            on_previous=lambda chart_win: self._navigate_chart(trade.trade_id, -1, chart_win),
            on_next=lambda chart_win: self._navigate_chart(trade.trade_id, +1, chart_win),
            has_previous=pos > 0,
            has_next=pos < total - 1,
            position_text=f"Trade {pos + 1} of {total} in current list",
        )

    def save_current_review(self):
        trade = self.selected_trade()
        if trade is None:
            messagebox.showinfo("Select a trade", "Select a trade before saving a review.")
            return
        save_review(
            config.REVIEWS_FILE,
            trade.trade_id,
            self.grade_var.get(),
            self.setup_var.get(),
            self.tag_var.get(),
            self.notes.get("1.0", tk.END).strip(),
        )
        self.reviews = load_reviews(config.REVIEWS_FILE)
        # Refresh only review columns without rereading the large market files.
        base_cols = [c for c in self.trades.columns if c not in ["process_grade", "setup", "mistake_tag", "notes", "updated_at"]]
        base = self.trades[base_cols].copy()
        self.trades = merge_reviews(base, self.reviews)
        self.apply_filters()
        if trade.trade_id in self.tree.get_children():
            self.tree.selection_set(trade.trade_id)
            self.tree.see(trade.trade_id)
        self.status_var.set("Review saved.")

    def sort_tree(self, col, reverse):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]

        def key(item):
            value = item[0]
            # Numeric-friendly sorting for P/L and prices.
            try:
                return (0, float(value.replace(",", "")))
            except Exception:
                return (1, value)

        items.sort(key=key, reverse=reverse)
        for index, (_, k) in enumerate(items):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self.sort_tree(col, not reverse))

    def show_stats(self):
        if self.trades.empty:
            return
        report = make_stats_report(self.trades)
        win = tk.Toplevel(self)
        win.title("Trade statistics")
        win.geometry("1050x780")
        text = tk.Text(win, wrap="none", font=("Consolas", 10))
        y = ttk.Scrollbar(win, orient=tk.VERTICAL, command=text.yview)
        x = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        text.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        win.rowconfigure(0, weight=1)
        win.columnconfigure(0, weight=1)
        text.insert("1.0", report)
        text.configure(state="disabled")


if __name__ == "__main__":

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = TradeReviewApp()
    app.mainloop()