from __future__ import annotations

import numpy as np
import pandas as pd


def _pf(group: pd.DataFrame):
    gross_win = group.loc[group.PL > 0, "PL"].sum()
    gross_loss = -group.loc[group.PL < 0, "PL"].sum()
    return gross_win / gross_loss if gross_loss > 0 else np.nan


def _summary(group: pd.DataFrame) -> str:
    n = len(group)
    if not n:
        return "0 trades"
    wins = (group.PL > 0).sum()
    avg = group.PL.mean()
    net = group.PL.sum()
    pf = _pf(group)
    pf_text = "—" if pd.isna(pf) else f"{pf:.2f}"
    return f"{n:4d} trades | Net R$ {net:9.2f} | Win {wins/n:5.1%} | Avg R$ {avg:7.2f} | PF {pf_text}"


def make_stats_report(df: pd.DataFrame) -> str:
    lines = []
    lines.append("TRADE REVIEW SUMMARY")
    lines.append("=" * 92)
    lines.append(_summary(df))
    days = max(df["Date"].nunique(), 1)
    lines.append(f"Trading days: {days} | Average trades/day: {len(df)/days:.1f} | Max trades in a day: {df.groupby('Date').size().max()}")
    lines.append("")

    lines.append("BY INSTRUMENT")
    for name, g in df.groupby("Root"):
        lines.append(f"{name:12s} {_summary(g)}")
    lines.append("")

    lines.append("BY SIDE")
    for name, g in df.groupby("Side"):
        lines.append(f"{name:12s} {_summary(g)}")
    lines.append("")

    period = pd.cut(df["EntryDT"].dt.hour + df["EntryDT"].dt.minute/60,
                    bins=[0, 10, 12, 14, 16, 24],
                    labels=["Before 10", "10-12", "12-14", "14-16", "After 16"], right=False)
    lines.append("BY ENTRY TIME")
    for name, g in df.assign(Period=period).groupby("Period", observed=False):
        if len(g):
            lines.append(f"{str(name):12s} {_summary(g)}")
    lines.append("")

    hold = pd.cut(df["DurationSec"], [-1, 60, 180, 600, np.inf],
                  labels=["< 1 min", "1-3 min", "3-10 min", "> 10 min"], right=False)
    lines.append("BY HOLDING TIME")
    for name, g in df.assign(Hold=hold).groupby("Hold", observed=False):
        if len(g):
            lines.append(f"{str(name):12s} {_summary(g)}")
    lines.append("")

    trade_bucket = pd.cut(df["TradeNoDay"], [0, 3, 6, 10, np.inf],
                          labels=["Trades 1-3", "Trades 4-6", "Trades 7-10", "Trade 11+"])
    lines.append("BY TRADE NUMBER WITHIN THE DAY")
    for name, g in df.assign(Bucket=trade_bucket).groupby("Bucket", observed=False):
        if len(g):
            lines.append(f"{str(name):12s} {_summary(g)}")
    lines.append("")

    gap_bucket = pd.cut(df["GapPrevSec"], [-np.inf, 60, 180, 600, np.inf],
                        labels=["< 1 min", "1-3 min", "3-10 min", "> 10 min"])
    lines.append("BY GAP SINCE PREVIOUS TRADE (possible re-entry / overtrading clue)")
    for name, g in df.assign(GapBucket=gap_bucket).groupby("GapBucket", observed=False):
        if len(g):
            lines.append(f"{str(name):12s} {_summary(g)}")
    lines.append("")

    reviewed = df[df["process_grade"].fillna("").ne("") & df["process_grade"].ne("Unreviewed")]
    lines.append("YOUR MANUAL PROCESS REVIEWS")
    if reviewed.empty:
        lines.append("No reviewed trades yet. Grade trades from the main screen; this section will populate automatically.")
    else:
        for name, g in reviewed.groupby("process_grade"):
            lines.append(f"{str(name):22s} {_summary(g)}")
        lines.append("")
        tagged = reviewed[reviewed["mistake_tag"].fillna("").ne("")]
        if not tagged.empty:
            lines.append("PRIMARY MISTAKE TAGS")
            for name, g in tagged.groupby("mistake_tag"):
                lines.append(f"{str(name)[:34]:34s} {_summary(g)}")

    lines.append("")
    lines.append("Interpretation rule: do not call a trade 'good' only because it won, or 'bad' only because it lost. Use the process grades and chart context to separate decision quality from outcome luck.")
    return "\n".join(lines)
