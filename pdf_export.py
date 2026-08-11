from __future__ import annotations

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from charting import create_trade_figure


def generate_monthly_pdfs(
    trades: pd.DataFrame,
    markets: dict[str, pd.DataFrame],
    output_dir: Path,
    status_callback=None,
) -> tuple[list[Path], list[str]]:
    """Create one PDF per month containing one existing trade chart per page.

    The chart itself is created by the same function used by the on-screen
    trade viewer, so this feature does not introduce a second chart layout.

    All loaded trades are exported, regardless of the current table filters.
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

    for period, month_df in df.groupby(df["EntryDT"].dt.to_period("M"), sort=True):
        pdf_path = pdf_dir / f"{period.strftime('%Y-%m')} Trade Review.pdf"

        if status_callback:
            status_callback(f"Creating {pdf_path.name} ({len(month_df)} trades)...")

        pages_written = 0

        with PdfPages(pdf_path) as pdf:
            pdf.infodict()["Title"] = f"My Trade Review - {period.strftime('%B %Y')}"
            pdf.infodict()["Author"] = "MyTradeReview"

            for _, trade in month_df.iterrows():
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
            # Do not leave an empty PDF behind if none of the month's trades
            # could be rendered.
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
        status_callback(
            f"Finished: {len(results)} monthly PDF(s) created in {pdf_dir}"
        )

    return results, problems
