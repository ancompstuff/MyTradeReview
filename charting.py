from __future__ import annotations

import math
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib.transforms import blended_transform_factory

from config import PRE_ENTRY_MINUTES, POST_EXIT_BARS, FIGSIZE, FIG_DPI, ANNOTATIONS_FILE, CHARTS_DIR
from annotations import load_annotations, save_annotations


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

    if "MA80" not in day.columns:
        day["MA80"] = day["Close"].rolling(MA_LONG_PERIOD, min_periods=1).mean()
    if "VWAP" not in day.columns:
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
    """Calculate trade metrics using only price information confirmed to occur while the trade was open.

    With 1-minute OHLC data, the exact intrabar sequence is unknown. Therefore the entry and
    exit candles are NOT used wholesale unless a full 1-minute bar is completely contained
    between the exact entry and exit timestamps. The actual entry and exit prices are always
    included because those prices are known to have occurred while the position was open.

    This deliberately produces a conservative (minimum confirmed) MFE/MAE for trades whose
    extrema may have occurred inside partial entry/exit candles. Tick data would be required
    for exact intrabar MFE/MAE.
    """
    entry_dt = pd.Timestamp(trade["EntryDT"])
    exit_dt = pd.Timestamp(trade["ExitDT"])
    entry_pos = _find_bar_pos(day, entry_dt)

    entry = float(trade["EntryPrice"])
    exitp = float(trade["ExitPrice"])
    long_trade = trade["Side"] == "LONG"

    # A 1-minute candle is safe only if the entire candle interval [start, start+1min]
    # was inside the holding period. This excludes price action before entry and after exit.
    bar_start = pd.to_datetime(day["DateTime"])
    bar_end = bar_start + pd.Timedelta(minutes=1)
    full_bar_mask = (bar_start >= entry_dt) & (bar_end <= exit_dt)
    full_bars = day.loc[full_bar_mask]

    # Entry and exit fills are indisputably prices reached while the trade existed.
    confirmed_high = max(entry, exitp)
    confirmed_low = min(entry, exitp)
    if not full_bars.empty:
        confirmed_high = max(confirmed_high, float(full_bars["High"].max()))
        confirmed_low = min(confirmed_low, float(full_bars["Low"].min()))

    if long_trade:
        mfe = confirmed_high - entry
        mae = entry - confirmed_low
        realized = exitp - entry
        favorable_level = confirmed_high
        adverse_level = confirmed_low
    else:
        mfe = entry - confirmed_low
        mae = confirmed_high - entry
        realized = entry - exitp
        favorable_level = confirmed_low
        adverse_level = confirmed_high

    mfe = max(float(mfe), 0.0)
    mae = max(float(mae), 0.0)
    capture = (realized / mfe * 100.0) if mfe > 0 else np.nan

    row = day.iloc[entry_pos]
    if long_trade:
        aligned = row["MA9"] >= row["MA20"]
    else:
        aligned = row["MA9"] <= row["MA20"]

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
        "favorable_level": favorable_level,
        "adverse_level": adverse_level,
        "full_bars_used": int(full_bar_mask.sum()),
    }


def _add_trade_extreme_lines(ax, trade: pd.Series, metrics: dict, entry_x: float, exit_x: float, n_bars: int):
    extend_to = min(n_bars - 0.35, exit_x + 3.0)
    start_at = max(0.0, entry_x)
    ax.hlines(metrics["favorable_level"], start_at, extend_to,
              colors="#15803d", linestyles="--", linewidth=1.2, zorder=4)
    ax.hlines(metrics["adverse_level"], start_at, extend_to,
              colors="#b91c1c", linestyles="--", linewidth=1.2, zorder=4)

    fav_label = f"Confirmed MFE {_price_fmt(trade['Root'], metrics['mfe'])}"
    adv_label = f"Confirmed MAE {_price_fmt(trade['Root'], metrics['mae'])}"
    ax.text(min(extend_to + 0.25, n_bars - 0.05), metrics["favorable_level"], fav_label,
            va="center", ha="left", fontsize=8.3, color="#166534",
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="#15803d", alpha=0.9))
    ax.text(min(extend_to + 0.25, n_bars - 0.05), metrics["adverse_level"], adv_label,
            va="center", ha="left", fontsize=8.3, color="#991b1b",
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="#b91c1c", alpha=0.9))


def _annotate_trade_points(ax, trade: pd.Series, entry_x: float, exit_x: float, n_bars: int):
    root = trade["Root"]
    entry_text = f"ENTRY  {trade['EntryDT']:%H:%M:%S}   {_price_fmt(root, trade['EntryPrice'])}"
    exit_text = f"EXIT  {trade['ExitDT']:%H:%M:%S}   {_price_fmt(root, trade['ExitPrice'])}"

    trans = blended_transform_factory(ax.transData, ax.transAxes)

    def _ha(x):
        if x <= n_bars * 0.20:
            return "left"
        if x >= n_bars * 0.80:
            return "right"
        return "center"

    def _x_adjust(x):
        if x <= n_bars * 0.08:
            return 1.2
        if x >= n_bars * 0.92:
            return n_bars - 1.2
        return x

    entry_anchor_x = _x_adjust(entry_x)
    exit_anchor_x = _x_adjust(exit_x)

    ax.annotate(entry_text,
                xy=(entry_x, trade["EntryPrice"]), xycoords="data",
                xytext=(entry_anchor_x, 0.965), textcoords=trans,
                ha=_ha(entry_x), va="top", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#374151", alpha=0.95),
                arrowprops=dict(arrowstyle="->", lw=0.8, color="#374151"),
                annotation_clip=False)

    ax.annotate(exit_text,
                xy=(exit_x, trade["ExitPrice"]), xycoords="data",
                xytext=(exit_anchor_x, 0.035), textcoords=trans,
                ha=_ha(exit_x), va="bottom", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#374151", alpha=0.95),
                arrowprops=dict(arrowstyle="->", lw=0.8, color="#374151"),
                annotation_clip=False)


def open_trade_chart(parent, market: pd.DataFrame, trade: pd.Series,
                     on_previous=None, on_next=None,
                     has_previous: bool = False, has_next: bool = False,
                     position_text: str = ""):

    try:
        day, window, _, _ = get_trade_window(market, trade)
        metrics = trade_metrics(day, trade)
    except Exception as exc:
        messagebox.showerror("Chart error", str(exc), parent=parent)
        return

    root = trade["Root"]
    win = tk.Toplevel(parent)
    win.title(f"{trade['Ativo']}  |  {trade['EntryDT']:%d/%m/%Y %H:%M:%S}  |  {trade['Side']}  |  P/L R$ {trade['PL']:.2f}")
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

    fig = Figure(figsize=FIGSIZE, dpi=FIG_DPI)
    gs = fig.add_gridspec(4, 1, height_ratios=[0.8, 6.3, 1.3, 0.55], hspace=0.03)
    axr = fig.add_subplot(gs[0])
    ax = fig.add_subplot(gs[1], sharex=axr)
    axv = fig.add_subplot(gs[2], sharex=axr)
    axi = fig.add_subplot(gs[3])
    axi.axis("off")

    x = np.arange(len(window))
    candle_width = 0.66

    # Thin RSI/IFR band.
    axr.plot(x, window["RSI14"], linewidth=1.0, color="#7c3aed")
    axr.axhline(70, color="#b91c1c", linewidth=0.8, linestyle="--")
    axr.axhline(30, color="#15803d", linewidth=0.8, linestyle="--")
    axr.set_ylim(0, 100)
    axr.set_ylabel("RSI", fontsize=8)
    axr.tick_params(axis="y", labelsize=8)

    # Candles.
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

    ax.plot(x, window["MA9"], linewidth=1.3, label="MA 9", color="#d97706")
    ax.plot(x, window["MA20"], linewidth=1.3, label="MA 20", color="#2563eb")
    ax.plot(x, window["MA80"], linewidth=1.25, label="MA 80", color="#111827")
    ax.plot(x, window["VWAP"], linewidth=2.8, label="Daily VWAP", color="#FFD700", zorder=4)
    ax.plot(x, window["DayHighKnown"], linewidth=1.0, label="Day high", color="#15803d")
    ax.plot(x, window["DayLowKnown"], linewidth=1.0, label="Day low", color="#991b1b")

    prev_high = window["PrevHigh"].dropna()
    prev_low = window["PrevLow"].dropna()
    if not prev_high.empty:
        ax.axhline(prev_high.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce", label="Prev session H/L")
    if not prev_low.empty:
        ax.axhline(prev_low.iloc[0], linestyle="--", linewidth=1.0, color="#7e22ce")

    # Highlight trade period and markers.
    entry_x = _fractional_x(window, trade["EntryDT"])
    exit_x = _fractional_x(window, trade["ExitDT"])
    entry_color = "#15803d" if trade["Side"] == "LONG" else "#b91c1c"
    ax.axvspan(entry_x, exit_x, color=entry_color, alpha=0.06, zorder=0)
    ax.scatter([entry_x], [trade["EntryPrice"]], s=90,
               marker="^" if trade["Side"] == "LONG" else "v",
               color=entry_color, edgecolor="black", linewidth=0.5, zorder=6)
    ax.scatter([exit_x], [trade["ExitPrice"]], s=75, marker="X",
               color="#111827", edgecolor="white", linewidth=0.5, zorder=6)

    _add_trade_extreme_lines(ax, trade, metrics, entry_x, exit_x, len(window))
    _annotate_trade_points(ax, trade, entry_x, exit_x, len(window))

    # Tighter y-scale so candles use vertical space better.
    visible_low = float(window["Low"].min())
    visible_high = float(window["High"].max())
    visible_span = max(visible_high - visible_low, 1.0)
    y_pad = visible_span * 0.04
    ax.set_ylim(visible_low - y_pad, visible_high + y_pad)

    result_word = "WIN" if trade["PL"] > 0 else "LOSS" if trade["PL"] < 0 else "FLAT"
    fig.suptitle(
        f"{trade['Ativo']}  {trade['EntryDT']:%d/%m/%Y}   {trade['Side']}   "
        f"Qty {trade['Qty']:.0f}   P/L R$ {trade['PL']:.2f} ({result_word})   "
        f"Hold {trade['Duration']}",
        x=0.07, ha="left", fontsize=12, fontweight="bold", y=0.985
    )
    ax.set_ylabel("Price")
    ax.legend(loc="upper left", fontsize=8, ncol=4, framealpha=0.9)

    volumes = window["Quantity"].fillna(0)
    axv.bar(x, volumes, width=0.66, color="#6b7280", align="center")
    axv.set_ylabel("Qty")

    # Shared time ticks and vertical grid so candles and volume line up visually.
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
        f"Confirmed MFE: {_price_fmt(root, metrics['mfe'])} pts     "
        f"Confirmed MAE: {_price_fmt(root, metrics['mae'])} pts     "
        f"MA9: {_price_fmt(root, metrics['ma9'])}     "
        f"MA20: {_price_fmt(root, metrics['ma20'])}     "
        f"MA80: {_price_fmt(root, metrics['ma80'])}     "
        f"VWAP: {_price_fmt(root, metrics['vwap'])}     "
        f"Capture of confirmed MFE: {capture_text}"
    )
    axi.text(0.01, 0.55, info_line, va="center", ha="left", fontsize=9.2,
             family="sans-serif", transform=axi.transAxes)

    fig.subplots_adjust(left=0.07, right=0.985, top=0.955, bottom=0.055, hspace=0.10)

    # -------- Persistent journal annotations --------
    annotation_bar = ttk.Frame(win, padding=(8, 3, 8, 3))
    annotation_bar.pack(fill=tk.X)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    state = {
        "mode": None,
        "arrow_start": None,
        "pen_points": [],
        "pen_artist": None,
        "artists": [],
        "items": load_annotations(ANNOTATIONS_FILE, str(trade["trade_id"])),
        "visible": True,
    }
    annotation_status = tk.StringVar(value="Annotation: off")

    def persist():
        save_annotations(ANNOTATIONS_FILE, str(trade["trade_id"]), state["items"])

    def clear_artists():
        for artist in state["artists"]:
            try:
                artist.remove()
            except Exception:
                pass
        state["artists"].clear()

    def draw_one(item):
        kind = item.get("type")
        artist = None
        if kind == "text":
            artist = ax.text(float(item["x"]), float(item["y"]), item.get("text", ""),
                             fontsize=9, zorder=20,
                             bbox=dict(boxstyle="round,pad=0.25", fc="#fffde7", ec="#374151", alpha=0.94))
        elif kind == "arrow":
            artist = FancyArrowPatch((float(item["x1"]), float(item["y1"])),
                                     (float(item["x2"]), float(item["y2"])),
                                     arrowstyle="->", mutation_scale=14, linewidth=1.8,
                                     color="#c2410c", zorder=19)
            ax.add_patch(artist)
        elif kind == "pen":
            pts = item.get("points", [])
            if len(pts) >= 2:
                xs = [float(pt[0]) for pt in pts]
                ys = [float(pt[1]) for pt in pts]
                artist, = ax.plot(xs, ys, linewidth=2.0, color="#c2410c", zorder=19)
        if artist is not None:
            artist.set_visible(state["visible"])
            state["artists"].append(artist)

    def redraw_annotations():
        clear_artists()
        for item in state["items"]:
            draw_one(item)
        canvas.draw_idle()

    def set_mode(mode):
        state["mode"] = mode
        state["arrow_start"] = None
        state["pen_points"] = []
        annotation_status.set(f"Annotation: {mode}" if mode else "Annotation: off")

    def undo_annotation():
        if not state["items"]:
            return
        state["items"].pop()
        persist()
        redraw_annotations()

    def clear_annotations():
        if not state["items"]:
            return
        if messagebox.askyesno("Clear annotations", "Remove all annotations from this trade?", parent=win):
            state["items"].clear()
            persist()
            redraw_annotations()

    def toggle_annotations():
        state["visible"] = not state["visible"]
        for artist in state["artists"]:
            artist.set_visible(state["visible"])
        toggle_btn.configure(text="Hide annotations" if state["visible"] else "Show annotations")
        canvas.draw_idle()

    def save_chart_image():
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        side = "L" if trade["Side"] == "LONG" else "S"
        filename = (f"{trade['EntryDT']:%Y-%m-%d_%H%M%S}_{trade['Root']}_{side}_"
                    f"{str(trade['trade_id'])}.png")
        path = CHARTS_DIR / filename
        fig.savefig(path, dpi=160, bbox_inches="tight")
        messagebox.showinfo("Chart saved", f"Saved to:\n{path}", parent=win)

    def on_press(event):
        if event.inaxes != ax or event.xdata is None or event.ydata is None:
            return
        mode = state["mode"]
        if mode == "Text":
            text = simpledialog.askstring("Chart comment", "Type your comment:", parent=win)
            if text and text.strip():
                state["items"].append({"type": "text", "x": float(event.xdata), "y": float(event.ydata), "text": text.strip()})
                persist()
                redraw_annotations()
            set_mode(None)
        elif mode == "Arrow":
            if state["arrow_start"] is None:
                state["arrow_start"] = (float(event.xdata), float(event.ydata))
                annotation_status.set("Annotation: Arrow — click end point")
            else:
                x1, y1 = state["arrow_start"]
                state["items"].append({"type": "arrow", "x1": x1, "y1": y1,
                                       "x2": float(event.xdata), "y2": float(event.ydata)})
                persist()
                redraw_annotations()
                set_mode(None)
        elif mode == "Pen":
            state["pen_points"] = [(float(event.xdata), float(event.ydata))]
            state["pen_artist"], = ax.plot([event.xdata], [event.ydata], linewidth=2.0, color="#c2410c", zorder=21)
            canvas.draw_idle()

    def on_motion(event):
        if state["mode"] != "Pen" or not state["pen_points"] or event.inaxes != ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        state["pen_points"].append((float(event.xdata), float(event.ydata)))
        artist = state["pen_artist"]
        if artist is not None:
            artist.set_data([p[0] for p in state["pen_points"]], [p[1] for p in state["pen_points"]])
            canvas.draw_idle()

    def on_release(event):
        if state["mode"] != "Pen" or not state["pen_points"]:
            return
        if state["pen_artist"] is not None:
            try:
                state["pen_artist"].remove()
            except Exception:
                pass
            state["pen_artist"] = None
        if len(state["pen_points"]) >= 2:
            # Reduce file size slightly while preserving the drawn shape.
            pts = state["pen_points"][::2] if len(state["pen_points"]) > 80 else state["pen_points"]
            state["items"].append({"type": "pen", "points": [[x, y] for x, y in pts]})
            persist()
            redraw_annotations()
        set_mode(None)

    ttk.Button(annotation_bar, text="Text", command=lambda: set_mode("Text")).pack(side=tk.LEFT, padx=2)
    ttk.Button(annotation_bar, text="Pen", command=lambda: set_mode("Pen")).pack(side=tk.LEFT, padx=2)
    ttk.Button(annotation_bar, text="Arrow", command=lambda: set_mode("Arrow")).pack(side=tk.LEFT, padx=2)
    ttk.Button(annotation_bar, text="Undo", command=undo_annotation).pack(side=tk.LEFT, padx=(10, 2))
    ttk.Button(annotation_bar, text="Clear", command=clear_annotations).pack(side=tk.LEFT, padx=2)
    toggle_btn = ttk.Button(annotation_bar, text="Hide annotations", command=toggle_annotations)
    toggle_btn.pack(side=tk.LEFT, padx=(10, 2))
    ttk.Button(annotation_bar, text="Save PNG", command=save_chart_image).pack(side=tk.LEFT, padx=2)
    ttk.Label(annotation_bar, textvariable=annotation_status).pack(side=tk.RIGHT, padx=8)

    canvas.mpl_connect("button_press_event", on_press)
    canvas.mpl_connect("motion_notify_event", on_motion)
    canvas.mpl_connect("button_release_event", on_release)

    redraw_annotations()
    canvas.draw()
    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()
    win.focus_set()
