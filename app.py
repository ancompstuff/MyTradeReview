from __future__ import annotations

import warnings

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
from datetime import datetime

import pandas as pd

import config
from data_loader import load_all, add_market_indicators
from charting import open_trade_chart, open_day_chart, open_scalp_chart
from reviews import load_reviews, save_review, merge_reviews
from stats import make_stats_report
from file_picker import ask_for_files
import tick_loader


def _ms(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts:%H:%M:%S}.{ts.microsecond // 1000:03d}"


class TradeReviewApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("My Trade Review - 2026")
        self.geometry("1600x900")
        self.minsize(1150, 700)

        self.trades = pd.DataFrame()
        self.markets = {}
        self.reviews = pd.DataFrame()
        self.view_df = pd.DataFrame()
        self.selected_trade_id = None
        self.current_market_choice = None
        self.current_trades_file = None
        self.current_market_file = None
        self.tick_parquet = None

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
        ttk.Button(top, text="Open day chart", command=self.open_day_chart).pack(side=tk.RIGHT, padx=3)

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

        ttk.Label(filters, text="Day:").pack(side=tk.LEFT)
        self.day_var = tk.StringVar(value="")
        self.day_combo = ttk.Combobox(filters, textvariable=self.day_var, values=[], width=12, state="readonly")
        self.day_combo.pack(side=tk.LEFT, padx=(4, 14))

        ttk.Label(filters, text="Tip: single-click to select/review; double-click opens grouped chart.").pack(side=tk.LEFT, padx=15)

        table_frame = ttk.Frame(self, padding=(8, 0, 8, 5))
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = [
            "Date", "EntryTime", "ExitTime", "Instrument", "Side", "Qty", "Leg",
            "Entry", "Exit", "Duration", "PL", "DayPL", "NoDay", "Gap", "Process", "Tag"
        ]
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        widths = {
            "Date": 90, "EntryTime": 110, "ExitTime": 110, "Instrument": 90, "Side": 65,
            "Qty": 40, "Leg": 55, "Entry": 85, "Exit": 85, "Duration": 78, "PL": 80,
            "DayPL": 90, "NoDay": 60, "Gap": 78, "Process": 120, "Tag": 180,
        }
        headings = {
            "Date": "Date", "EntryTime": "Entry time", "ExitTime": "Exit time", "Instrument": "Contract",
            "Side": "Side", "Qty": "Qty", "Leg": "Leg", "Entry": "Entry", "Exit": "Exit",
            "Duration": "Hold", "PL": "P/L R$", "DayPL": "Day P/L after", "NoDay": "Trade #",
            "Gap": "Gap prev", "Process": "Process", "Tag": "Primary tag",
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

        # Alternate shade per entry group + win/loss color
        self.tree.tag_configure("Win0", background="#eef9ee")
        self.tree.tag_configure("Win1", background="#d8f0d8")
        self.tree.tag_configure("Loss0", background="#fff0f0")
        self.tree.tag_configure("Loss1", background="#f8dddd")
        self.tree.tag_configure("Flat0", background="#f7f7f7")
        self.tree.tag_configure("Flat1", background="#ececec")

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

        trades_file, market_choice, data_file, source = choice

        try:
            self.tick_parquet = None
            market_df = None

            if source == "tick":
                self.status_var.set("Preparing tick file (first time may take a while)...")
                self.update_idletasks()
                self.tick_parquet = tick_loader.ensure_parquet(data_file)

                self.status_var.set("Building 1-minute bars from tick file...")
                self.update_idletasks()
                minute_df = tick_loader.minute_bars(self.tick_parquet)
                market_df = add_market_indicators(minute_df, config.MA_FAST, config.MA_SLOW)

            self.status_var.set("Reading trades...")
            self.update_idletasks()

            trades, markets = load_all(
                trades_file=trades_file,
                market_choice=market_choice,
                market_file=None if source == "tick" else data_file,
                fast_ma=config.MA_FAST,
                slow_ma=config.MA_SLOW,
                market_df=market_df,
            )

            self.markets = markets
            self.reviews = load_reviews(config.REVIEWS_FILE)
            self.trades = merge_reviews(trades, self.reviews)

            self._refresh_instrument_filter_values()
            self.apply_filters()
            self.update_summary()

            root = next(iter(markets.keys()))
            n_positions = self.trades["PositionId"].nunique() if "PositionId" in self.trades.columns else len(self.trades)
            self.status_var.set(
                f"Loaded {len(self.trades)} legs ({n_positions} entries) | {market_choice} bars: {len(markets[root]):,} | "
                f"Source: {'Tick CSV' if source == 'tick' else '1-minute CSV'}"
            )
        except Exception as exc:
            self.tick_parquet = None
            messagebox.showerror("Could not load files", str(exc))
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
            if r.Root == "WIN":
                entry_fmt = f"{r.EntryPrice:,.0f}"
                exit_fmt = f"{r.ExitPrice:,.0f}"
            else:
                entry_fmt = f"{r.EntryPrice:,.2f}"
                exit_fmt = f"{r.ExitPrice:,.2f}"

            pos_qty = int(r.PositionQty) if pd.notna(r.get("PositionQty")) else int(r.Qty)
            leg_text = f"{int(r.LegNo)}/{pos_qty}" if pos_qty > 1 else ""
            shade = int(r.GroupNo) % 2
            process_short = r.process_grade.replace(" - ", " ")

            vals = (
                r.EntryDT.strftime("%d/%m/%Y"),
                _ms(r.EntryDT),
                _ms(r.ExitDT),
                r.Ativo,
                r.Side,
                f"{r.Qty:.0f}",
                leg_text,
                entry_fmt,
                exit_fmt,
                r.Duration,
                f"{r.PL:.2f}",
                f"{r.DayPLAfter:.2f}",
                f"{int(r.TradeNoDay)}/{int(r.TradesDay)}",
                r.GapPrev,
                process_short,
                r.mistake_tag,
            )
            self.tree.insert("", tk.END, iid=r.trade_id, values=vals, tags=(f"{r.Outcome}{shade}",))
        self._refresh_day_values()

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
            f"Selected {trade.Ativo} {trade.EntryDT:%d/%m/%Y} {_ms(trade.EntryDT)} | {trade.Side} | P/L R$ {trade.PL:.2f}"
        )
        self.day_var.set(trade.EntryDT.strftime("%d/%m/%Y"))

    def _group_for(self, trade):
        if "PositionId" not in self.trades.columns:
            return self.trades[self.trades.trade_id == trade.trade_id].copy()
        pid = trade.get("PositionId")
        if pd.isna(pid):
            return self.trades[self.trades.trade_id == trade.trade_id].copy()
        same = self.trades[self.trades["PositionId"] == pid].copy()
        return same.sort_values("ExitDT").reset_index(drop=True)

    def _chart_trade_ids_in_current_order(self):
        return list(self.tree.get_children(""))

    def _navigate_chart(self, current_trade_id, direction, chart_window):
        ids = self._chart_trade_ids_in_current_order()
        if current_trade_id not in ids:
            return

        pos_by_id = self.trades.set_index("trade_id")["PositionId"].to_dict() if "PositionId" in self.trades.columns else {}
        cur_pid = pos_by_id.get(current_trade_id)

        idx = ids.index(current_trade_id) + direction
        while 0 <= idx < len(ids) and cur_pid is not None and pos_by_id.get(ids[idx]) == cur_pid:
            idx += direction
        if idx < 0 or idx >= len(ids):
            return

        next_id = ids[idx]
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

        group = self._group_for(trade)
        group_df = group if len(group) > 1 else None
        last_exit = group["ExitDT"].max()
        group_duration = max((last_exit - trade.EntryDT).total_seconds(), 0.0)

        ids = self._chart_trade_ids_in_current_order()
        pos_by_id = self.trades.set_index("trade_id")["PositionId"].to_dict() if "PositionId" in self.trades.columns else {}
        cur_pid = pos_by_id.get(trade.trade_id)
        pos = ids.index(trade.trade_id) if trade.trade_id in ids else 0

        def _has(direction):
            i = pos + direction
            while 0 <= i < len(ids) and cur_pid is not None and pos_by_id.get(ids[i]) == cur_pid:
                i += direction
            return 0 <= i < len(ids)

        has_prev, has_next = _has(-1), _has(+1)
        n_entries = len({pos_by_id.get(i, i) for i in ids}) if pos_by_id else len(ids)
        entry_no = len({pos_by_id.get(i, i) for i in ids[:pos + 1]}) if pos_by_id else pos + 1
        position_text = f"Entry {entry_no} of {n_entries} in current list"
        if group_df is not None:
            position_text += f"   ({len(group_df)} contracts)"

        prev_cb = lambda w: self._navigate_chart(trade.trade_id, -1, w)
        next_cb = lambda w: self._navigate_chart(trade.trade_id, +1, w)

        if self.tick_parquet is not None and group_duration <= config.SCALP_AUTO_MAX_SEC:
            try:
                tick_size = config.TICK_SIZE.get(trade.Root, 0.01)
                span_trade = trade.copy()
                span_trade["ExitDT"] = last_exit
                bars, v0, v1 = tick_loader.prepare_scalp_bars(self.tick_parquet, span_trade, tick_size)
                open_scalp_chart(
                    self, trade, bars, v0, v1, tick_size,
                    on_previous=prev_cb, on_next=next_cb,
                    has_previous=has_prev, has_next=has_next,
                    position_text=position_text, group=group_df,
                )
                return
            except Exception as exc:
                messagebox.showerror("Scalp chart error", str(exc))
                return

        market = self.markets.get(trade.Root)
        if market is None:
            messagebox.showerror("No data", f"No market data loaded for {trade.Root}.")
            return

        open_trade_chart(
            self, market, trade,
            on_previous=prev_cb, on_next=next_cb,
            has_previous=has_prev, has_next=has_next,
            position_text=position_text,
            trade_group=group_df,
        )

    def _day_values(self):
        if self.trades.empty:
            return []
        return [d.strftime("%d/%m/%Y") for d in sorted(self.trades["Date"].unique())]

    def _refresh_day_values(self):
        values = self._day_values()
        self.day_combo.configure(values=values)
        if not values:
            self.day_var.set("")
        elif self.day_var.get() not in values:
            self.day_var.set(values[-1])

    def open_day_chart(self, day_text=None):
        values = self._day_values()
        day_text = day_text or self.day_var.get()
        if not day_text or day_text not in values:
            messagebox.showinfo("Select a day", "Choose a day in the Day dropdown first.")
            return

        session_date = datetime.strptime(day_text, "%d/%m/%Y").date()
        day_trades = self.view_df[self.view_df["Date"] == session_date]
        if day_trades.empty:
            messagebox.showinfo("No trades", f"No trades on {day_text}.")
            return

        root = day_trades.iloc[0]["Root"]
        market = self.markets.get(root)
        if market is None:
            messagebox.showerror("No data", f"No market data loaded for {root}.")
            return

        pos = values.index(day_text)
        open_day_chart(
            self, market, day_trades, session_date,
            on_previous=lambda w: self._navigate_day(day_text, -1, w),
            on_next=lambda w: self._navigate_day(day_text, +1, w),
            has_previous=pos > 0,
            has_next=pos < len(values) - 1,
            position_text=f"Day {pos + 1} of {len(values)}  ({day_text})",
        )

    def _navigate_day(self, current_text, direction, chart_window):
        values = self._day_values()
        if current_text not in values:
            return
        target = values.index(current_text) + direction
        if target < 0 or target >= len(values):
            return
        if chart_window is not None and chart_window.winfo_exists():
            chart_window.destroy()
        self.day_var.set(values[target])
        self.open_day_chart(values[target])

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