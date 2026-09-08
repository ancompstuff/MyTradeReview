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
    """Export trade charts to PDF.

    If split_by_month is True, creates one PDF per month.
    If split_by_month is False, exports all trades into a single PDF file.
    """
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

    # Group trades by month or combine into one group
    if split_by_month:
        groups = [(period.strftime('%Y-%m'), group) for period, group in
                  df.groupby(df["EntryDT"].dt.to_period("M"), sort=True)]
    else:
        date_range = f"{df['EntryDT'].min():%Y%m%d}_to_{df['EntryDT'].max():%Y%m%d}"
        groups = [(date_range, df)]

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
                    fig = create_trade_figure(market, trade)  # Fixed typo here
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