from __future__ import annotations

from dataclasses import dataclass
from html import escape
import math
import pandas as pd
import numpy as np


@dataclass
class SummaryMetrics:
    trades: int
    wins: int
    losses: int
    flats: int
    win_rate: float
    net_pl: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    avg_trade: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float
    largest_win: float
    largest_loss: float
    max_win_streak: int
    max_loss_streak: int
    avg_hold_seconds: float
    avg_win_hold_seconds: float
    avg_loss_hold_seconds: float
    max_qty: float
    max_drawdown: float
    max_single_trade_decline: float


def _safe_mean(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return float(series.mean())


def _streak(values, predicate) -> int:
    best = current = 0
    for value in values:
        if predicate(value):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def calculate_summary(df: pd.DataFrame) -> SummaryMetrics:
    if df.empty:
        return SummaryMetrics(
            trades=0, wins=0, losses=0, flats=0, win_rate=float("nan"), net_pl=0.0,
            gross_profit=0.0, gross_loss=0.0, profit_factor=float("nan"), avg_trade=float("nan"),
            avg_win=float("nan"), avg_loss=float("nan"), win_loss_ratio=float("nan"),
            largest_win=float("nan"), largest_loss=float("nan"), max_win_streak=0,
            max_loss_streak=0, avg_hold_seconds=float("nan"), avg_win_hold_seconds=float("nan"),
            avg_loss_hold_seconds=float("nan"), max_qty=float("nan"), max_drawdown=0.0,
            max_single_trade_decline=0.0,
        )

    work = df.sort_values(["EntryDT", "ExitDT"]).copy()
    pl = pd.to_numeric(work["PL"], errors="coerce").fillna(0.0)
    winners = pl[pl > 0]
    losers = pl[pl < 0]
    equity = pl.cumsum()
    peaks = equity.cummax().clip(lower=0.0)
    dd = equity - peaks

    avg_win = _safe_mean(winners)
    avg_loss = _safe_mean(losers)
    gross_profit = float(winners.sum())
    gross_loss = abs(float(losers.sum()))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("nan")
    ratio = avg_win / abs(avg_loss) if not math.isnan(avg_win) and not math.isnan(avg_loss) and avg_loss != 0 else float("nan")

    dur = pd.to_numeric(work.get("DurationSec", pd.Series(index=work.index, dtype=float)), errors="coerce")
    qty = pd.to_numeric(work.get("Qty", pd.Series(index=work.index, dtype=float)), errors="coerce")

    return SummaryMetrics(
        trades=int(len(work)),
        wins=int((pl > 0).sum()),
        losses=int((pl < 0).sum()),
        flats=int((pl == 0).sum()),
        win_rate=float((pl > 0).mean()),
        net_pl=float(pl.sum()),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=pf,
        avg_trade=float(pl.mean()),
        avg_win=avg_win,
        avg_loss=avg_loss,
        win_loss_ratio=ratio,
        largest_win=float(winners.max()) if not winners.empty else float("nan"),
        largest_loss=float(losers.min()) if not losers.empty else float("nan"),
        max_win_streak=_streak(pl.tolist(), lambda x: x > 0),
        max_loss_streak=_streak(pl.tolist(), lambda x: x < 0),
        avg_hold_seconds=_safe_mean(dur.dropna()),
        avg_win_hold_seconds=_safe_mean(dur[pl > 0].dropna()),
        avg_loss_hold_seconds=_safe_mean(dur[pl < 0].dropna()),
        max_qty=float(qty.max()) if qty.notna().any() else float("nan"),
        max_drawdown=float(dd.min()) if not dd.empty else 0.0,
        max_single_trade_decline=float(min(pl.min(), 0.0)) if not pl.empty else 0.0,
    )


def money(v: float) -> str:
    if pd.isna(v):
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(v: float, decimals=2) -> str:
    if pd.isna(v):
        return "—"
    return f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{v * 100:.1f}%".replace(".", ",")


def duration(seconds: float) -> str:
    if pd.isna(seconds):
        return "—"
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _metric_table(metrics: SummaryMetrics) -> str:
    left = [
        ("Resultado", money(metrics.net_pl)),
        ("Lucro bruto", money(metrics.gross_profit)),
        ("Fator de lucro", num(metrics.profit_factor)),
        ("Número de operações", str(metrics.trades)),
        ("Operações vencedoras", str(metrics.wins)),
        ("Operações zeradas", str(metrics.flats)),
        ("Média lucro/prejuízo", money(metrics.avg_trade)),
        ("Média vencedoras", money(metrics.avg_win)),
        ("Maior vencedora", money(metrics.largest_win)),
        ("Maior sequência vencedora", str(metrics.max_win_streak)),
        ("Média tempo vencedoras", duration(metrics.avg_win_hold_seconds)),
        ("Tempo médio operação", duration(metrics.avg_hold_seconds)),
        ("Máximo contratos", num(metrics.max_qty, 0)),
    ]
    right = [
        ("Prejuízo bruto", money(-metrics.gross_loss)),
        ("Percentual vencedoras", pct(metrics.win_rate)),
        ("Operações perdedoras", str(metrics.losses)),
        ("Razão média lucro:média prejuízo", num(metrics.win_loss_ratio)),
        ("Média perdedoras", money(metrics.avg_loss)),
        ("Maior perdedora", money(metrics.largest_loss)),
        ("Maior sequência perdedora", str(metrics.max_loss_streak)),
        ("Média tempo perdedoras", duration(metrics.avg_loss_hold_seconds)),
        ("Declínio máximo topo ao fundo", money(metrics.max_drawdown)),
        ("Maior queda em uma operação", money(metrics.max_single_trade_decline)),
        ("Custos", "— (não disponíveis no CSV de operações)"),
    ]
    rows = []
    n = max(len(left), len(right))
    for i in range(n):
        l = left[i] if i < len(left) else ("", "")
        r = right[i] if i < len(right) else ("", "")
        rows.append(
            "<tr>"
            f"<td style='padding:4px 12px 4px 0'><b>{escape(l[0])}</b></td>"
            f"<td style='padding:4px 28px 4px 0'>{escape(l[1])}</td>"
            f"<td style='padding:4px 12px 4px 0'><b>{escape(r[0])}</b></td>"
            f"<td style='padding:4px 0'>{escape(r[1])}</td>"
            "</tr>"
        )
    return "<table style='border-collapse:collapse;font-family:Segoe UI;font-size:10pt'>" + "".join(rows) + "</table>"


def _trade_title(row: pd.Series) -> str:
    n = int(row.get("TradeNoDay", 0) or 0)
    return f"Trade {n:02d} - {row['Ativo']} - {row['EntryDT']:%H:%M:%S}"


def trade_table_html(df: pd.DataFrame, page_links: dict[str, str] | None = None) -> str:
    page_links = page_links or {}
    headers = ["#", "Data", "Hora", "Ativo", "Lado", "Qtd", "Entrada", "Saída", "Tempo", "P/L"]
    th = "".join(f"<th style='border:1px solid #bbb;padding:4px;background:#eee'>{h}</th>" for h in headers)
    rows = []
    work = df.sort_values(["EntryDT", "ExitDT"])
    for _, r in work.iterrows():
        tid = str(r["trade_id"])
        title = escape(_trade_title(r))
        url = page_links.get(tid)
        first = f"<a href='{escape(url, quote=True)}'>{title}</a>" if url else title
        side = "LONG" if r["Side"] == "LONG" else "SHORT"
        vals = [
            first,
            r["EntryDT"].strftime("%d/%m/%Y"),
            r["EntryDT"].strftime("%H:%M:%S"),
            escape(str(r["Ativo"])), side, num(float(r.get("Qty", np.nan)), 0),
            num(float(r["EntryPrice"]), 1 if r["Root"] == "WDO" else 0),
            num(float(r["ExitPrice"]), 1 if r["Root"] == "WDO" else 0),
            escape(str(r.get("Duration", ""))), money(float(r["PL"])),
        ]
        rows.append("<tr>" + "".join(f"<td style='border:1px solid #bbb;padding:4px'>{v}</td>" for v in vals) + "</tr>")
    return (
        "<table style='border-collapse:collapse;font-family:Segoe UI;font-size:9pt'>"
        f"<tr>{th}</tr>{''.join(rows)}</table>"
    )


def summary_body_html(df: pd.DataFrame, heading: str, page_links: dict[str, str] | None = None) -> str:
    metrics = calculate_summary(df)
    return (
        "<div data-id='journal-summary'>"
        f"<h2>{escape(heading)}</h2>"
        f"{_metric_table(metrics)}"
        "<p><b>Operações</b></p>"
        f"{trade_table_html(df, page_links)}"
        "<p style='font-size:8pt;color:#666'>"
        "Observação: custos/corretagem não são inferidos porque o CSV de operações fornecido não contém um campo de custos por operação."
        "</p>"
        "</div>"
    )


def page_html(title: str, body_html: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        f"<title>{escape(title)}</title>"
        "</head><body>"
        f"{body_html}"
        "</body></html>"
    )
