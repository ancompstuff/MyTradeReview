"""Export generated trade charts as monthly or combined PDF reports."""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from charting import create_trade_figure


def generate_trade_pdfs(
    trades: pd.DataFrame,
    markets: dict[str, pd.DataFrame],
    output_dir: Path,
    status_callback=None,
    prefix: str = "Trade Review",
    split_by_month: bool = True,
) -> tuple[list[Path], list[str]]:
    if trades is None or trades.empty:
        raise ValueError("There are no trades loaded.")

    df = trades.copy()
    df["EntryDT"] = pd.to_datetime(df["EntryDT"], errors="coerce")
    df = df.dropna(subset=["EntryDT"]).sort_values("EntryDT")

    pdf_dir = Path(output_dir) / "PDFs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    problems: list[str] = []

    safe_prefix = "".join(c for c in prefix if c.isalnum() or c in (" ", "_", "-")).strip()

    if split_by_month:
        groups = [(period.strftime('%Y-%m'), group) for period, group in df.groupby(df["EntryDT"].dt.to_period("M"), sort=True)]
    else:
        groups = [("All_Selected", df)]

    for group_key, group_df in groups:
        if split_by_month:
            pdf_path = pdf_dir / f"{group_key} - {safe_prefix}.pdf"
            pdf_title = f"{safe_prefix} - {group_key}"
        else:
            pdf_path = pdf_dir / f"{safe_prefix} ({len(group_df)} Trades).pdf"
            pdf_title = f"{safe_prefix} - All Selected Trades"

        if status_callback:
            status_callback(f"Creating {pdf_path.name} ({len(group_df)} trades)...")

        pages_written = 0

        with PdfPages(pdf_path) as pdf:
            pdf.infodict()["Title"] = pdf_title
            pdf.infodict()["Author"] = "MyTradeReview"

            for _, trade in group_df.iterrows():
                market = markets.get(trade["Root"])
                if market is None or market.empty:
                    problems.append(
                        f"{trade['Ativo']} {trade['EntryDT']:%d/%m/%Y %H:%M:%S}: "
                        f"no {trade['Root']} market data loaded"
                    )
                    continue

                try:
                    fig = create_trade_figure(market, trade)
                    pdf.savefig(fig)
                    plt.close(fig)
                    pages_written += 1
                except Exception as exc:
                    problems.append(
                        f"{trade['Ativo']} {trade['EntryDT']:%d/%m/%Y %H:%M:%S}: {exc}"
                    )

        if pages_written:
            results.append(pdf_path)
        else:
            try:
                pdf_path.unlink()
            except FileNotFoundError:
                pass

    if not results:
        detail = "\n".join(problems[:10])
        raise RuntimeError(
            "No trade charts could be written to PDF."
            + (f"\n\n{detail}" if detail else "")
        )

    if status_callback:
        status_callback(f"Finished: {len(results)} PDF(s) created in {pdf_dir}")

    return results, problems


def generate_daily_trade_pdf(
    day_trades: pd.DataFrame,
    markets: dict[str, pd.DataFrame],
    pdf_path: str | Path,
    tick_parquet: Path | None = None,
    status_callback=None,
) -> tuple[Path, list[str]]:
    """Write a day overview, statistics page, and individual trade plots to one A4 PDF."""
    import tick_loader
    import config
    from charting import create_day_figure, create_trade_figure, create_scalp_figure
    from stats import create_stats_figure

    if day_trades is None or day_trades.empty:
        raise ValueError("There are no trades for the selected day.")

    output = Path(pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    day_trades = day_trades.copy().sort_values("EntryDT").reset_index(drop=True)
    session_date = pd.Timestamp(day_trades["EntryDT"].iloc[0]).date()
    problems: list[str] = []
    pages_written = 0

    if status_callback:
        status_callback("Creating daily overview page...")

    with PdfPages(output) as pdf:
        pdf.infodict()["Title"] = f"Daily Trade Review - {session_date:%d/%m/%Y}"
        pdf.infodict()["Author"] = "MyTradeReview"

        roots = day_trades["Root"].dropna().unique().tolist()
        overview_market = next((markets.get(root) for root in roots if markets.get(root) is not None), None)
        if overview_market is not None:
            try:
                fig = create_day_figure(overview_market, day_trades, session_date)
                pdf.savefig(fig, orientation="landscape", bbox_inches="tight")
                plt.close(fig)
                pages_written += 1
            except Exception as exc:
                problems.append(f"Could not create day overview: {exc}")
        else:
            problems.append("Could not create day overview: no market data loaded.")

        if status_callback:
            status_callback("Creating statistics page...")
        try:
            fig = create_stats_figure(day_trades, f"Daily statistics - {session_date:%d/%m/%Y}")
            pdf.savefig(fig, orientation="landscape", bbox_inches="tight")
            plt.close(fig)
            pages_written += 1
        except Exception as exc:
            problems.append(f"Could not create statistics page: {exc}")

        if "PositionId" in day_trades.columns:
            groups = []
            for _, group in day_trades.groupby("PositionId", sort=False):
                if group.empty:
                    continue
                groups.append(group.sort_values("ExitDT").reset_index(drop=True))
        else:
            groups = [day_trades.loc[[i]].copy() for i in range(len(day_trades))]

        for index, group in enumerate(groups, start=1):
            trade = group.iloc[0]
            if status_callback:
                status_callback(f"Creating individual trade page {index} of {len(groups)}...")

            market = markets.get(trade["Root"])
            if market is None or market.empty:
                problems.append(f"Trade {trade['Ativo']} {trade['EntryDT']}: no market data loaded")
                continue

            try:
                group_duration = max((group["ExitDT"].max() - trade["EntryDT"]).total_seconds(), 0.0)
                fig = None
                if tick_parquet is not None and group_duration <= config.SCALP_AUTO_MAX_SEC:
                    tick_size = config.TICK_SIZE.get(trade["Root"], 0.01)
                    span_trade = trade.copy()
                    span_trade["ExitDT"] = group["ExitDT"].max()
                    bars, view_start, view_end = tick_loader.prepare_scalp_bars(tick_parquet, span_trade, tick_size)
                    fig = create_scalp_figure(trade, bars, view_start, view_end, tick_size, group=group)
                else:
                    fig = create_trade_figure(market, trade)

                pdf.savefig(fig, orientation="landscape", bbox_inches="tight")
                plt.close(fig)
                pages_written += 1
            except Exception as exc:
                problems.append(f"Trade {trade['Ativo']} {trade['EntryDT']}: {exc}")

    if pages_written == 0:
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise RuntimeError("No PDF pages could be created.")

    if status_callback:
        status_callback(f"Finished: PDF created at {output}")
    return output, problems