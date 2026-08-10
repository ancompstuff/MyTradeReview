from __future__ import annotations

from io import BytesIO
import math
import numpy as np
import pandas as pd

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.transforms import blended_transform_factory

from charting import get_trade_window, trade_metrics, _fractional_x


def _price_fmt(root: str, value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:,.0f}" if root == "WIN" else f"{value:,.1f}"


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_down = down.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).bfill()


def render_trade_chart_png(market: pd.DataFrame, trade: pd.Series, dpi: int = 135) -> bytes:
    day, window, _, _ = get_trade_window(market, trade)
    metrics = trade_metrics(day, trade)
    if "RSI14" not in window.columns:
        window = window.copy()
        window["RSI14"] = _rsi(window["Close"])

    fig = Figure(figsize=(12, 9), dpi=dpi)
    gs = fig.add_gridspec(4, 1, height_ratios=[0.8, 6.3, 1.3, 0.55], hspace=0.03)
    axr = fig.add_subplot(gs[0])
    ax = fig.add_subplot(gs[1], sharex=axr)
    axv = fig.add_subplot(gs[2], sharex=axr)
    axi = fig.add_subplot(gs[3])
    axi.axis("off")

    x = np.arange(len(window))
    axr.plot(x, window["RSI14"], linewidth=1.0, color="#7c3aed")
    axr.axhline(70, color="#b91c1c", linewidth=0.8, linestyle="--")
    axr.axhline(30, color="#15803d", linewidth=0.8, linestyle="--")
    axr.set_ylim(0, 100)
    axr.set_ylabel("RSI", fontsize=8)
    axr.tick_params(axis="y", labelsize=8)

    price_span = max(float(window["High"].max() - window["Low"].min()), 1.0)
    min_body = price_span * 0.00035
    candle_width = 0.66
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

    entry_x = _fractional_x(window, trade["EntryDT"])
    exit_x = _fractional_x(window, trade["ExitDT"])
    entry_color = "#15803d" if trade["Side"] == "LONG" else "#b91c1c"
    ax.axvspan(entry_x, exit_x, color=entry_color, alpha=0.06, zorder=0)
    ax.scatter([entry_x], [trade["EntryPrice"]], s=90,
               marker="^" if trade["Side"] == "LONG" else "v",
               color=entry_color, edgecolor="black", linewidth=0.5, zorder=6)
    ax.scatter([exit_x], [trade["ExitPrice"]], s=75, marker="X",
               color="#111827", edgecolor="white", linewidth=0.5, zorder=6)

    extend_to = min(len(window) - 0.35, exit_x + 3.0)
    ax.hlines(metrics["favorable_level"], entry_x, extend_to, colors="#15803d", linestyles="--", linewidth=1.2, zorder=4)
    ax.hlines(metrics["adverse_level"], entry_x, extend_to, colors="#b91c1c", linestyles="--", linewidth=1.2, zorder=4)
    label_x = min(extend_to + 0.25, len(window) - 0.05)
    ax.text(label_x, metrics["favorable_level"], f"Confirmed MFE {_price_fmt(trade['Root'], metrics['mfe'])}",
            va="center", ha="left", fontsize=8.1, color="#166534",
            bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="#15803d", alpha=0.9))
    ax.text(label_x, metrics["adverse_level"], f"Confirmed MAE {_price_fmt(trade['Root'], metrics['mae'])}",
            va="center", ha="left", fontsize=8.1, color="#991b1b",
            bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="#b91c1c", alpha=0.9))

    trans = blended_transform_factory(ax.transData, ax.transAxes)
    ax.annotate(f"ENTRY {trade['EntryDT']:%H:%M:%S}  {_price_fmt(trade['Root'], trade['EntryPrice'])}",
                xy=(entry_x, trade["EntryPrice"]), xycoords="data", xytext=(entry_x, 0.965), textcoords=trans,
                ha="center", va="top", fontsize=8.3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#374151", alpha=0.95),
                arrowprops=dict(arrowstyle="->", lw=0.8, color="#374151"), annotation_clip=False)
    ax.annotate(f"EXIT {trade['ExitDT']:%H:%M:%S}  {_price_fmt(trade['Root'], trade['ExitPrice'])}",
                xy=(exit_x, trade["ExitPrice"]), xycoords="data", xytext=(exit_x, 0.035), textcoords=trans,
                ha="center", va="bottom", fontsize=8.3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#374151", alpha=0.95),
                arrowprops=dict(arrowstyle="->", lw=0.8, color="#374151"), annotation_clip=False)

    visible_low = float(window["Low"].min())
    visible_high = float(window["High"].max())
    y_pad = max(visible_high - visible_low, 1.0) * 0.04
    ax.set_ylim(visible_low - y_pad, visible_high + y_pad)

    result_word = "WIN" if trade["PL"] > 0 else "LOSS" if trade["PL"] < 0 else "FLAT"
    fig.suptitle(
        f"{trade['Ativo']}  {trade['EntryDT']:%d/%m/%Y}   {trade['Side']}   Qty {trade['Qty']:.0f}   "
        f"P/L R$ {trade['PL']:.2f} ({result_word})   Hold {trade['Duration']}",
        x=0.07, ha="left", fontsize=12, fontweight="bold", y=0.985,
    )
    ax.set_ylabel("Price")
    ax.legend(loc="upper left", fontsize=8, ncol=4, framealpha=0.9)

    axv.bar(x, window["Quantity"].fillna(0), width=0.66, color="#6b7280", align="center")
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

    capture = "—" if pd.isna(metrics["capture"]) else f"{metrics['capture']:.0f}%"
    axi.text(
        0.01, 0.55,
        f"Realized move: {_price_fmt(trade['Root'], metrics['realized'])} pts     "
        f"Confirmed MFE: {_price_fmt(trade['Root'], metrics['mfe'])} pts     "
        f"Confirmed MAE: {_price_fmt(trade['Root'], metrics['mae'])} pts     "
        f"MA9: {_price_fmt(trade['Root'], metrics['ma9'])}     MA20: {_price_fmt(trade['Root'], metrics['ma20'])}     "
        f"MA80: {_price_fmt(trade['Root'], metrics['ma80'])}     VWAP: {_price_fmt(trade['Root'], metrics['vwap'])}     "
        f"Capture of MFE: {capture}",
        va="center", ha="left", fontsize=9.0, transform=axi.transAxes,
    )

    fig.subplots_adjust(left=0.07, right=0.985, top=0.955, bottom=0.055, hspace=0.10)
    out = BytesIO()
    fig.savefig(out, format="png", dpi=dpi, bbox_inches="tight")
    return out.getvalue()
