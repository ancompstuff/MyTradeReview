from __future__ import annotations

import math
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Rectangle, Patch
from matplotlib.transforms import blended_transform_factory

import config
from config import PRE_ENTRY_MINUTES, POST_EXIT_BARS, FIGSIZE, FIG_DPI

RSI_PERIOD = 14
MA_LONG_PERIOD = 80


def _price_fmt(root: str, value: float) -> str:
    if pd.isna(value):
        return "—"
    if root == "WIN":
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _find_bar_pos(day: pd.DataFrame, dt: pd.Timestamp) -> int:
    minute = pd.Timestamp(dt).floor("min")
    exact = np.flatnonzero(day["DateTime"].values == np.datetime64(minute))
    if len(exact):
        return int(exact[0])
    delta = (day["DateTime"] - minute).abs()
    return int(delta.argmin())


def _fractional_x(window: pd.DataFrame, dt: pd.Timestamp) -> float:
    minute = pd.Timestamp(dt).floor("min")
    matches = np.flatnonzero(window["DateTime"].values == np.datetime64(minute))
    if len(matches):
        seconds = (pd.Timestamp(dt) - minute).total_seconds()
        return float(matches[0]) + min(max(seconds / 60.0, 0.0), 0.98)
    delta = (window["DateTime"] - minute).abs()
    return float(delta.argmin())


def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_down = down.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill()


def get_trade_window(market: pd.DataFrame, trade: pd.Series):
    session_date = trade["EntryDT"].date()
    day = market[market["SessionDate"] == session_date].copy().reset_index(drop=True)
    if day.empty:
        raise ValueError(f"No {trade['Root']} 1-minute data found for {session_date:%d/%m/%Y}.")

    if "RSI14" not in day.columns:
        day["RSI14"] = _rsi(day["Close"], RSI_PERIOD)

    day["MA80"] = day["Close"].rolling(MA_LONG_PERIOD, min_periods=1).mean()

    typical_price = (day["High"] + day["Low"] + day["Close"]) / 3.0
    vwap_weight = day["Quantity"].fillna(0).clip(lower=0)
    cumulative_weight = vwap_weight.cumsum()
    cumulative_pv = (typical_price * vwap_weight).cumsum()
    day["VWAP"] = cumulative_pv.div(cumulative_weight.replace(0, np.nan)).ffill()

    entry_pos = _find_bar_pos(day, trade["EntryDT"])
    exit_pos = _find_bar_pos(day, trade["ExitDT"])
    start_time = trade["EntryDT"] - pd.Timedelta(minutes=PRE_ENTRY_MINUTES)
    candidate = np.flatnonzero(day["DateTime"].values >= np.datetime64(start_time.floor("min")))
    start_pos = int(candidate[0]) if len(candidate) else 0
    start_pos = min(start_pos, entry_pos)
    end_pos = min(len(day) - 1, exit_pos + POST_EXIT_BARS)

    window = day.iloc[start_pos:end_pos + 1].copy().reset_index(drop=True)
    return day, window, entry_pos, exit_pos


def trade_metrics(day: pd.DataFrame, trade: pd.Series):
    entry_pos = _find_bar_pos(day, trade["EntryDT"])
    exit_pos = _find_bar_pos(day, trade["ExitDT"])
    lo, hi = sorted((entry_pos, exit_pos))
    held = day.iloc[lo:hi + 1]
    entry = float(trade["EntryPrice"])
    exitp = float(trade["ExitPrice"])
    long_trade = trade["Side"] == "LONG"

    if long_trade:
        mfe = held["High"].max() - entry
        mae = entry - held["Low"].min()
        realized = exitp - entry
    else:
        mfe = entry - held["Low"].min()
        mae = held["High"].max() - entry
        realized = entry - exitp

    mfe = max(float(mfe), 0.0)
    mae = max(float(mae), 0.0)
    capture = (realized / mfe * 100.0) if mfe > 0 else np.nan

    row = day.iloc[entry_pos]
    aligned = (row["MA9"] >= row["MA20"]) if long_trade else (row["MA9"] <= row["MA20"])

    return {
        "mfe": mfe,
        "mae": mae,
        "realized": realized,
        "capture": capture,
        "ma9": row["MA9"],
        "ma20": row["MA20"],
        "ma80": row["MA80"],
        "vwap": row["VWAP"],
        "aligned": bool(aligned),
        "day_high": row["DayHighKnown"],
        "day_low": row["DayLowKnown"],
        "prev_high": row["PrevHigh"],
        "prev_low": row["PrevLow"],
    }


def _annotate_trade_points(ax, trade: pd.Series, entry_x: float, exit_x: float, entry_y: float, exit_y: float,
                           n_bars: int):
    root = trade["Root"]
    entry_text = f"ENTRY  {trade['EntryDT']:%H:%M:%S}   {_price_fmt(root, trade['EntryPrice'])}"
    exit_text = f"EXIT  {trade['ExitDT']:%H:%M:%S}   {_price_fmt(root, trade['ExitPrice'])}"

    trans = blended_transform_factory(ax.transData, ax.transAxes)

    def _ha(x):
        if x <= n_bars * 0.18:
            return "left"
        if x >= n_bars * 0.82:
            return "right"
        return "center"

    is_long = trade["Side"] == "LONG"
    entry_color = "#15803d" if is_long else "#b91c1c"
    exit_color = "#b91c1c" if is_long else "#15803d"

    # ENTRY Box pointing directly to trade entry level on candles
    ax.annotate(
        entry_text,
        xy=(entry_x, entry_y), xycoords="data",
        xytext=(entry_x, 0.82), textcoords=trans,
        ha=_ha(entry_x), va="top", fontsize=8.5, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=entry_color, lw=1.2, alpha=0.95),
        arrowprops=dict(arrowstyle="->", lw=1.0, color=entry_color),
        zorder=8,
    )

    # EXIT Box pointing directly to trade exit level on candles
    ax.annotate(
        exit_text,
        xy=(exit_x, exit_y), xycoords="data",
        xytext=(exit_x, 0.08), textcoords=trans,
        ha=_ha(exit_x), va="bottom", fontsize=8.5, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=exit_color, lw=1.2, alpha=0.95),
        arrowprops=dict(arrowstyle="->", lw=1.0, color=exit_color),
        zorder=8,
    )


def create_trade_figure(market: pd.DataFrame, trade: pd.Series):
    """Create chart figure with entry-to-exit price/time box anchored directly to candle price action."""
    day, window, entry_bar_pos, exit_bar_pos = get_trade_window(market, trade)
    metrics = trade_metrics(day, trade)
    root = trade["Root"]

    fig = Figure(figsize=FIGSIZE, dpi=FIG_DPI)
    gs = fig.add_gridspec(4, 1, height_ratios=[0.8, 6.3, 1.3, 0.55], hspace=0.03)
    axr = fig.add_subplot(gs[0])
    ax = fig.add_subplot(gs[1], sharex=axr)
    axv = fig.add_subplot(gs[2], sharex=axr)
    axi = fig.add_subplot(gs[3])
    axi.axis("off")

    x = np.arange(len(window))
    candle_width = 0.66

    # RSI Band
    axr.plot(x, window["RSI14"], linewidth=1.0, color="#7c3aed")
    axr.axhline(70, color="#b91c1c", linewidth=0.8, linestyle="--")
    axr.axhline(30, color="#15803d", linewidth=0.8, linestyle="--")
    axr.set_ylim(0, 100)
    axr.set_ylabel("RSI", fontsize=8)
    axr.tick_params(axis="y", labelsize=8)

    # Candlesticks
    price_span = max(window["High"].max() - window["Low"].min(), 1.0)
    min_body = price_span * 0.00035
    for i, row in window.iterrows():
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        ax.vlines(i, l, h, color="black", linewidth=0.8, zorder=2)
        lower = min(o, c)
        height = max(abs(c - o), min_body)
        face = "white" if c >= o else "black"
        ax.add_patch(Rectangle((i - candle_width / 2, lower), candle_width, height,
                               facecolor=face, edgecolor="black", linewidth=0.8, zorder=3))

    # Moving Averages & Levels
    ax.plot(x, window["MA9"], linewidth=1.3, label="MA 9", color="#d97706")
    ax.plot(x, window["MA20"], linewidth=1.3, label="MA 20", color="#2563eb")
    ax.plot(x, window["MA80"], linewidth=1.25, label="MA 80", color="#111827")
    ax.plot(x, window["VWAP"], linewidth=2, label="Daily VWAP", color="yellow")
    ax.plot(x, window["DayHighKnown"], linewidth=1.0, label="Day high", color="#15803d")
    ax.plot(x, window["DayLowKnown"], linewidth=1.0, label="Day low", color="#991b1b")

    prev_high = window["PrevHigh"].dropna()
    prev_low = window["PrevLow"].dropna()
    if not prev_high.empty:
        ax.axhline(prev_high.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce", label="Prev session H/L")
    if not prev_low.empty:
        ax.axhline(prev_low.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce")

    # Time coordinates
    entry_x = _fractional_x(window, trade["EntryDT"])
    exit_x = _fractional_x(window, trade["ExitDT"])

    # Candle price anchoring logic:
    # 1. Take entry bar Open price on the chart as the visual entry baseline
    entry_bar = day.iloc[entry_bar_pos]
    candle_entry_p = float(entry_bar["Open"])

    # 2. Add the actual points realized/lost in the trade to determine visual exit level on candles
    is_long = trade["Side"] == "LONG"
    pts_change = (float(trade["ExitPrice"]) - float(trade["EntryPrice"])) if is_long else (
                float(trade["EntryPrice"]) - float(trade["ExitPrice"]))
    candle_exit_p = candle_entry_p + (pts_change if is_long else -pts_change)

    box_x = entry_x
    box_w = max(exit_x - entry_x, 0.25)
    box_y = min(candle_entry_p, candle_exit_p)
    box_h = max(abs(candle_exit_p - candle_entry_p), price_span * 0.008)

    box_color = "#15803d" if trade["PL"] >= 0 else "#b91c1c"

    trade_box = Rectangle(
        (box_x, box_y), box_w, box_h,
        facecolor=box_color, alpha=0.30,
        edgecolor=box_color, linestyle="--", linewidth=1.8,
        zorder=5, label="Trade Box"
    )
    ax.add_patch(trade_box)

    # ENTRY / EXIT text annotations pointing directly to the candle entry & exit prices
    _annotate_trade_points(ax, trade, entry_x, exit_x, candle_entry_p, candle_exit_p, len(window))

    # Y-axis bounds lock strictly to the candle window
    visible_low = float(window["Low"].min())
    visible_high = float(window["High"].max())
    visible_span = max(visible_high - visible_low, 1.0)
    ax.set_ylim(visible_low - visible_span * 0.05, visible_high + visible_span * 0.15)

    result_word = "WIN" if trade["PL"] > 0 else "LOSS" if trade["PL"] < 0 else "FLAT"
    fig.suptitle(
        f"{trade['Ativo']}  {trade['EntryDT']:%d/%m/%Y}   {trade['Side']}   "
        f"Qty {trade['Qty']:.0f}   P/L R$ {trade['PL']:.2f} ({result_word})   "
        f"Hold {trade['Duration']}",
        x=0.07, ha="left", fontsize=12, fontweight="bold", y=0.985
    )
    ax.set_ylabel("Price")

    ax.legend(loc="upper right", fontsize=8, ncol=4, framealpha=0.9)

    # Volume Subplot
    volumes = window["Quantity"].fillna(0)
    axv.bar(x, volumes, width=0.66, color="#6b7280", align="center")
    axv.set_ylabel("Qty")

    step = max(1, math.ceil(len(window) / 12))
    ticks = list(range(0, len(window), step))
    if len(window) - 1 not in ticks:
        ticks.append(len(window) - 1)
    labels = [window.iloc[i]["DateTime"].strftime("%H:%M") for i in ticks]
    axv.set_xticks(ticks)
    axv.set_xticklabels(labels, fontsize=8)
    axr.set_xticks(ticks)
    ax.tick_params(labelbottom=False)
    axr.tick_params(labelbottom=False)

    for axis in (axr, ax, axv):
        axis.set_axisbelow(True)
        axis.grid(True, axis="y", alpha=0.18)
        axis.grid(True, axis="x", alpha=0.11)
        axis.margins(x=0.01)

    capture_text = "—" if pd.isna(metrics["capture"]) else f"{metrics['capture']:.0f}%"
    info_line = (
        f"Realized move: {_price_fmt(root, metrics['realized'])} pts     "
        f"MFE: {_price_fmt(root, metrics['mfe'])} pts     "
        f"MAE: {_price_fmt(root, metrics['mae'])} pts     "
        f"MA9: {_price_fmt(root, metrics['ma9'])}     "
        f"MA20: {_price_fmt(root, metrics['ma20'])}     "
        f"MA80: {_price_fmt(root, metrics['ma80'])}     "
        f"VWAP: {_price_fmt(root, metrics['vwap'])}     "
        f"Capture of MFE: {capture_text}"
    )
    axi.text(0.01, 0.55, info_line, va="center", ha="left", fontsize=9.2,
             family="sans-serif", transform=axi.transAxes)

    fig.subplots_adjust(left=0.07, right=0.985, top=0.955, bottom=0.055, hspace=0.10)

    return fig


def open_trade_chart(parent, market: pd.DataFrame, trade: pd.Series,
                     on_previous=None, on_next=None,
                     has_previous: bool = False, has_next: bool = False,
                     position_text: str = ""):
    try:
        fig = create_trade_figure(market, trade)
    except Exception as exc:
        messagebox.showerror("Chart error", str(exc), parent=parent)
        return

    win = tk.Toplevel(parent)
    win.title(
        f"{trade['Ativo']}  |  {trade['EntryDT']:%d/%m/%Y %H:%M:%S}  |  {trade['Side']}  |  P/L R$ {trade['PL']:.2f}")
    win.geometry("1280x960")

    nav = ttk.Frame(win, padding=(8, 6))
    nav.pack(fill=tk.X)
    prev_btn = ttk.Button(nav, text="◀  Previous trade", width=18)
    prev_btn.pack(side=tk.LEFT)
    if on_previous is not None:
        prev_btn.configure(command=lambda: on_previous(win))
    if not has_previous:
        prev_btn.state(["disabled"])

    ttk.Label(nav, text=position_text, anchor=tk.CENTER,
              font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, expand=True, fill=tk.X)

    next_btn = ttk.Button(nav, text="Next trade  ▶", width=18)
    next_btn.pack(side=tk.RIGHT)
    if on_next is not None:
        next_btn.configure(command=lambda: on_next(win))
    if not has_next:
        next_btn.state(["disabled"])

    if on_previous is not None and has_previous:
        win.bind("<Left>", lambda _e: on_previous(win))
    if on_next is not None and has_next:
        win.bind("<Right>", lambda _e: on_next(win))

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()
    win.focus_set()

def _prepare_day(market: pd.DataFrame, session_date) -> pd.DataFrame:
    day = market[market["SessionDate"] == session_date].copy().reset_index(drop=True)
    if day.empty:
        raise ValueError(f"No 1-minute data found for {session_date:%d/%m/%Y}.")

    if "RSI14" not in day.columns:
        day["RSI14"] = _rsi(day["Close"], RSI_PERIOD)
    day["MA80"] = day["Close"].rolling(MA_LONG_PERIOD, min_periods=1).mean()

    typical_price = (day["High"] + day["Low"] + day["Close"]) / 3.0
    weight = day["Quantity"].fillna(0).clip(lower=0)
    day["VWAP"] = (typical_price * weight).cumsum().div(weight.cumsum().replace(0, np.nan)).ffill()
    return day


def open_day_chart(parent, market: pd.DataFrame, trades_day: pd.DataFrame, session_date,
                   on_previous=None, on_next=None,
                   has_previous: bool = False, has_next: bool = False,
                   position_text: str = ""):
    """Draw the full session with every trade of that day marked on it."""
    try:
        day = _prepare_day(market, session_date)
    except Exception as exc:
        messagebox.showerror("Chart error", str(exc), parent=parent)
        return

    trades_day = trades_day.sort_values("EntryDT").reset_index(drop=True)
    root = trades_day.iloc[0]["Root"]

    win = tk.Toplevel(parent)
    net = float(trades_day["PL"].sum())
    win.title(f"{session_date:%d/%m/%Y}  |  {len(trades_day)} trades  |  Net R$ {net:.2f}")
    win.geometry("1400x980")

    nav = ttk.Frame(win, padding=(8, 6))
    nav.pack(fill=tk.X)
    prev_btn = ttk.Button(nav, text="◀  Previous day", width=18)
    prev_btn.pack(side=tk.LEFT)
    if on_previous is not None:
        prev_btn.configure(command=lambda: on_previous(win))
    if not has_previous:
        prev_btn.state(["disabled"])

    ttk.Label(nav, text=position_text, anchor=tk.CENTER,
              font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, expand=True, fill=tk.X)

    next_btn = ttk.Button(nav, text="Next day  ▶", width=18)
    next_btn.pack(side=tk.RIGHT)
    if on_next is not None:
        next_btn.configure(command=lambda: on_next(win))
    if not has_next:
        next_btn.state(["disabled"])

    if on_previous is not None and has_previous:
        win.bind("<Left>", lambda _e: on_previous(win))
    if on_next is not None and has_next:
        win.bind("<Right>", lambda _e: on_next(win))

    fig = Figure(figsize=(14, 9.5), dpi=FIG_DPI)
    gs = fig.add_gridspec(5, 1, height_ratios=[0.8, 6.0, 1.2, 1.5, 0.5], hspace=0.03)
    axr = fig.add_subplot(gs[0])
    ax = fig.add_subplot(gs[1], sharex=axr)
    axv = fig.add_subplot(gs[2], sharex=axr)
    axp = fig.add_subplot(gs[3], sharex=axr)
    axi = fig.add_subplot(gs[4])
    axi.axis("off")

    n = len(day)
    x = np.arange(n)
    candle_width = 0.66

    # RSI
    axr.plot(x, day["RSI14"], linewidth=1.0, color="#7c3aed")
    axr.axhline(70, color="#b91c1c", linewidth=0.8, linestyle="--")
    axr.axhline(30, color="#15803d", linewidth=0.8, linestyle="--")
    axr.set_ylim(0, 100)
    axr.set_ylabel("RSI", fontsize=8)
    axr.tick_params(axis="y", labelsize=8)

    # Candles
    price_span = max(day["High"].max() - day["Low"].min(), 1.0)
    min_body = price_span * 0.00035
    ax.vlines(x, day["Low"], day["High"], color="black", linewidth=0.7, zorder=2)
    for i, row in day.iterrows():
        o, c = row["Open"], row["Close"]
        face = "white" if c >= o else "black"
        ax.add_patch(Rectangle((i - candle_width / 2, min(o, c)), candle_width,
                               max(abs(c - o), min_body),
                               facecolor=face, edgecolor="black", linewidth=0.6, zorder=3))

    ax.plot(x, day["MA9"], linewidth=1.1, label="MA 9", color="#d97706")
    ax.plot(x, day["MA20"], linewidth=1.1, label="MA 20", color="#2563eb")
    ax.plot(x, day["MA80"], linewidth=1.1, label="MA 80", color="#111827")
    ax.plot(x, day["VWAP"], linewidth=1.8, label="Daily VWAP", color="yellow")
    ax.plot(x, day["DayHighKnown"], linewidth=0.9, label="Day high", color="#15803d")
    ax.plot(x, day["DayLowKnown"], linewidth=0.9, label="Day low", color="#991b1b")

    prev_high = day["PrevHigh"].dropna()
    prev_low = day["PrevLow"].dropna()
    if not prev_high.empty:
        ax.axhline(prev_high.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce", label="Prev session H/L")
    if not prev_low.empty:
        ax.axhline(prev_low.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce")

    # Trades
    cum = 0.0
    cum_x = [0.0]
    cum_y = [0.0]
    for k, t in trades_day.iterrows():
        ex = _fractional_x(day, t["EntryDT"])
        xx = _fractional_x(day, t["ExitDT"])
        pl = float(t["PL"]) if pd.notna(t["PL"]) else 0.0
        color = "#15803d" if pl > 0 else "#b91c1c" if pl < 0 else "#6b7280"
        long_trade = t["Side"] == "LONG"

        ax.axvspan(ex, max(xx, ex + 0.3), color=color, alpha=0.07, zorder=0)
        ax.plot([ex, xx], [t["EntryPrice"], t["ExitPrice"]],
                color=color, linewidth=1.8, zorder=5)
        ax.scatter([ex], [t["EntryPrice"]], s=70, marker="^" if long_trade else "v",
                   color=color, edgecolor="black", linewidth=0.5, zorder=6)
        ax.scatter([xx], [t["ExitPrice"]], s=55, marker="X",
                   color="#111827", edgecolor="white", linewidth=0.5, zorder=6)
        offset = 12 if long_trade else -14
        ax.annotate(f"#{k + 1}  {pl:+.0f}", xy=(ex, t["EntryPrice"]),
                    xytext=(0, offset), textcoords="offset points",
                    ha="center", va="bottom" if long_trade else "top",
                    fontsize=7.5, color=color, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.12", fc="white", ec=color, alpha=0.85),
                    zorder=7)

        cum += pl
        cum_x.append(xx)
        cum_y.append(cum)

    low = float(day["Low"].min())
    high = float(day["High"].max())
    pad = max(high - low, 1.0) * 0.05
    ax.set_ylim(low - pad, high + pad)
    ax.set_ylabel("Price")
    ax.legend(loc="upper left", fontsize=8, ncol=4, framealpha=0.9)

    # Volume
    axv.bar(x, day["Quantity"].fillna(0), width=0.66, color="#6b7280", align="center")
    axv.set_ylabel("Qty")

    # Cumulative P/L
    cum_x.append(float(n - 1))
    cum_y.append(cum)
    axp.step(cum_x, cum_y, where="post", color="#2563eb", linewidth=1.5)
    axp.axhline(0, color="#374151", linewidth=0.8)
    axp.fill_between(cum_x, cum_y, 0, step="post", alpha=0.12,
                     color="#15803d" if cum >= 0 else "#b91c1c")
    axp.set_ylabel("Cum P/L R$", fontsize=8)
    axp.tick_params(axis="y", labelsize=8)

    # Shared time axis
    step = max(1, math.ceil(n / 14))
    ticks = list(range(0, n, step))
    if n - 1 not in ticks:
        ticks.append(n - 1)
    labels = [day.iloc[i]["DateTime"].strftime("%H:%M") for i in ticks]
    axp.set_xticks(ticks)
    axp.set_xticklabels(labels, fontsize=8)
    for a in (axr, ax, axv):
        a.tick_params(labelbottom=False)
    for a in (axr, ax, axv, axp):
        a.set_axisbelow(True)
        a.grid(True, axis="y", alpha=0.18)
        a.grid(True, axis="x", alpha=0.11)
        a.margins(x=0.01)

    wins = int((trades_day["PL"] > 0).sum())
    losses = int((trades_day["PL"] < 0).sum())
    best = float(trades_day["PL"].max())
    worst = float(trades_day["PL"].min())
    fig.suptitle(
        f"{session_date:%A %d/%m/%Y}   {len(trades_day)} trades   "
        f"Net R$ {net:.2f}   ({wins}W / {losses}L)",
        x=0.07, ha="left", fontsize=12, fontweight="bold", y=0.985,
    )
    info = (f"Best trade: R$ {best:.2f}     Worst trade: R$ {worst:.2f}     "
            f"Day high: {_price_fmt(root, high)}     Day low: {_price_fmt(root, low)}")
    axi.text(0.01, 0.55, info, va="center", ha="left", fontsize=9.2, transform=axi.transAxes)

    fig.subplots_adjust(left=0.07, right=0.985, top=0.955, bottom=0.05, hspace=0.10)
    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()
    win.focus_set()

def _runs(mask):
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def _add_nav_bar(win, on_previous, on_next, has_previous, has_next, position_text, noun="trade"):
    nav = ttk.Frame(win, padding=(8, 6))
    nav.pack(fill=tk.X)
    prev_btn = ttk.Button(nav, text=f"◀  Previous {noun}", width=18)
    prev_btn.pack(side=tk.LEFT)
    if on_previous is not None:
        prev_btn.configure(command=lambda: on_previous(win))
    if not has_previous:
        prev_btn.state(["disabled"])
    ttk.Label(nav, text=position_text, anchor=tk.CENTER,
              font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, expand=True, fill=tk.X)
    next_btn = ttk.Button(nav, text=f"Next {noun}  ▶", width=18)
    next_btn.pack(side=tk.RIGHT)
    if on_next is not None:
        next_btn.configure(command=lambda: on_next(win))
    if not has_next:
        next_btn.state(["disabled"])
    if on_previous is not None and has_previous:
        win.bind("<Left>", lambda _e: on_previous(win))
    if on_next is not None and has_next:
        win.bind("<Right>", lambda _e: on_next(win))


def _flow_summary_lines(bars: pd.DataFrame, trade: pd.Series, bar_sec: float):
    entry = pd.Timestamp(trade["EntryDT"])
    entry_bar = entry.floor(pd.Timedelta(seconds=bar_sec))
    sign = 1 if trade["Side"] == "LONG" else -1
    before = bars[bars["DateTime"] < entry_bar]   # strictly before the entry second
    if before.empty:
        return ["No flow data before entry."]

    def window(sec):
        return before[before["DateTime"] >= entry_bar - pd.Timedelta(seconds=sec)]

    d10, d30, d60 = (float(window(s)["Delta"].sum()) for s in (10, 30, 60))
    verdict = "WITH" if sign * d30 > 0 else "AGAINST" if sign * d30 < 0 else "NEUTRAL to"

    avg30 = bars["Qty"].sum() / max(len(bars) * bar_sec / 30.0, 1.0)
    pace = float(window(30)["Qty"].sum()) / avg30 if avg30 > 0 else float("nan")

    w30 = window(30)
    flags = []
    if w30["BullS"].any(): flags.append("selling absorbed (5s)")
    if w30["BearS"].any(): flags.append("buying absorbed (5s)")
    if w30["BullL"].any(): flags.append("accumulation (60s)")
    if w30["BearL"].any(): flags.append("distribution (60s)")
    flags_text = ", ".join(flags) if flags else "none"

    return [
        f"Delta before entry:  10s {d10:+,.0f}   30s {d30:+,.0f}   60s {d60:+,.0f}   "
        f"-> 30s flow is {verdict} your {trade['Side']}",
        f"Cum delta at entry: {float(before['CumDelta'].iloc[-1]):+,.0f}     "
        f"Tape pace (30s): x{pace:.1f} of average     Absorption in last 30s: {flags_text}",
    ]


def open_scalp_chart(parent, trade: pd.Series, bars: pd.DataFrame, view_start, view_end,
                     tick_size: float, on_previous=None, on_next=None,
                     has_previous: bool = False, has_next: bool = False,
                     position_text: str = ""):
    bar_sec = float((bars["DateTime"].iloc[1] - bars["DateTime"].iloc[0]).total_seconds())
    v = bars[(bars["DateTime"] >= view_start) & (bars["DateTime"] < view_end)].reset_index(drop=True)
    if v.empty:
        messagebox.showerror("Chart error", "No tick data in the selected window.", parent=parent)
        return

    root = trade["Root"]
    win = tk.Toplevel(parent)
    win.title(f"SCALP  |  {trade['Ativo']}  |  {trade['EntryDT']:%d/%m/%Y %H:%M:%S}  |  "
              f"{trade['Side']}  |  P/L R$ {trade['PL']:.2f}")
    win.geometry("1400x980")
    _add_nav_bar(win, on_previous, on_next, has_previous, has_next, position_text)

    fig = Figure(figsize=(14, 9.5), dpi=config.FIG_DPI)
    gs = fig.add_gridspec(5, 1, height_ratios=[5.0, 1.5, 1.4, 1.6, 0.8], hspace=0.04)
    ax = fig.add_subplot(gs[0])
    axv = fig.add_subplot(gs[1], sharex=ax)
    axd = fig.add_subplot(gs[2], sharex=ax)
    axc = fig.add_subplot(gs[3], sharex=ax)
    axi = fig.add_subplot(gs[4])
    axi.axis("off")

    n = len(v)
    x = np.arange(n) + 0.5

    def xpos(dt):
        return (pd.Timestamp(dt) - view_start).total_seconds() / bar_sec

    # Candles
    span = max(v["High"].max() - v["Low"].min(), tick_size)
    min_body = max(span * 0.002, tick_size * 0.15)
    w = 0.7
    ax.vlines(x, v["Low"], v["High"], color="black", linewidth=0.7, zorder=2)
    for i in range(n):
        o, c = v.at[i, "Open"], v.at[i, "Close"]
        ax.add_patch(Rectangle((x[i] - w / 2, min(o, c)), w, max(abs(c - o), min_body),
                               facecolor="white" if c >= o else "black",
                               edgecolor="black", linewidth=0.5, zorder=3))

    # Absorption zones
    for s, e in _runs(v["BullS"].values):
        for a in (ax, axv):
            a.axvspan(s, e, color="#0891b2", alpha=0.13, zorder=0)
    for s, e in _runs(v["BearS"].values):
        for a in (ax, axv):
            a.axvspan(s, e, color="#c026d3", alpha=0.13, zorder=0)
    for s, e in _runs(v["BullL"].values):
        ax.axvspan(s, e, ymin=0.95, ymax=1.0, color="#0891b2", alpha=0.55, zorder=1)
    for s, e in _runs(v["BearL"].values):
        ax.axvspan(s, e, ymin=0.95, ymax=1.0, color="#c026d3", alpha=0.55, zorder=1)

    # Trade markers
    ex, xx = xpos(trade["EntryDT"]), xpos(trade["ExitDT"])
    long_trade = trade["Side"] == "LONG"
    color = "#15803d" if trade["Side"] == "LONG" else "#b91c1c"
    ax.plot([ex, xx], [trade["EntryPrice"], trade["ExitPrice"]], color=color, linewidth=2, zorder=5)
    ax.scatter([ex], [trade["EntryPrice"]], s=110, marker="^" if long_trade else "v",
               color=color, edgecolor="black", linewidth=0.6, zorder=6)
    ax.scatter([xx], [trade["ExitPrice"]], s=90, marker="X",
               color="#111827", edgecolor="white", linewidth=0.6, zorder=6)
    ax.annotate(f"ENTRY {trade['EntryDT']:%H:%M:%S}  {_price_fmt(root, trade['EntryPrice'])}",
                xy=(ex, trade["EntryPrice"]), xytext=(-10, 28 if long_trade else -28),
                textcoords="offset points", ha="right", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#374151"),
                arrowprops=dict(arrowstyle="->", lw=0.8), zorder=8)
    ax.annotate(f"EXIT {trade['ExitDT']:%H:%M:%S}  {_price_fmt(root, trade['ExitPrice'])}",
                xy=(xx, trade["ExitPrice"]), xytext=(10, -28 if long_trade else 28),
                textcoords="offset points", ha="left", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#374151"),
                arrowprops=dict(arrowstyle="->", lw=0.8), zorder=8)

    pad = span * 0.06
    ax.set_ylim(v["Low"].min() - pad, v["High"].max() + pad)
    ax.set_ylabel("Price")
    ax.legend(handles=[
        Patch(color="#0891b2", alpha=0.4, label="Selling absorbed (bullish)"),
        Patch(color="#c026d3", alpha=0.4, label="Buying absorbed (bearish)"),
    ], loc="upper left", fontsize=8, framealpha=0.9)

    # Aggressor volume
    axv.bar(x, v["BuyVol"], width=0.85, color="#15803d")
    axv.bar(x, -v["SellVol"], width=0.85, color="#b91c1c")
    axv.axhline(0, color="#374151", linewidth=0.6)
    axv.set_ylabel("Aggr vol", fontsize=8)

    # Delta and cumulative delta
    axd.bar(x, v["Delta"], width=0.85, color=np.where(v["Delta"] >= 0, "#15803d", "#b91c1c"))
    axd.axhline(0, color="#374151", linewidth=0.6)
    axd.set_ylabel("Delta", fontsize=8)

    axc.plot(x, v["CumDelta"], color="#2563eb", linewidth=1.4)
    axc.set_ylabel("Cum delta", fontsize=8)

    for a in (ax, axv, axd, axc):
        a.axvline(ex, color=color, linewidth=1.0, linestyle=":")
        a.axvline(xx, color="#111827", linewidth=1.0, linestyle=":")
        a.set_axisbelow(True)
        a.grid(True, axis="y", alpha=0.18)
        a.grid(True, axis="x", alpha=0.11)
        a.margins(x=0.005)
        a.tick_params(axis="y", labelsize=8)
    for a in (ax, axv, axd):
        a.tick_params(labelbottom=False)

    step = max(1, int(round(15 / bar_sec)))
    ticks = list(range(0, n, step))
    axc.set_xticks([t + 0.5 for t in ticks])
    axc.set_xticklabels([v.iloc[t]["DateTime"].strftime("%H:%M:%S") for t in ticks], fontsize=8)

    result_word = "WIN" if trade["PL"] > 0 else "LOSS" if trade["PL"] < 0 else "FLAT"
    fig.suptitle(
        f"{trade['Ativo']}  {trade['EntryDT']:%d/%m/%Y}   {trade['Side']}   Qty {trade['Qty']:.0f}   "
        f"P/L R$ {trade['PL']:.2f} ({result_word})   Hold {trade['Duration']}",
        x=0.07, ha="left", fontsize=12, fontweight="bold", y=0.985)

    lines = _flow_summary_lines(bars, trade, bar_sec)
    axi.text(0.01, 0.5, "\n".join(lines), va="center", ha="left", fontsize=9.5, transform=axi.transAxes)

    fig.subplots_adjust(left=0.07, right=0.985, top=0.955, bottom=0.05)
    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    NavigationToolbar2Tk(canvas, win).update()
    win.focus_set()