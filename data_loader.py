from __future__ import annotations

import hashlib
from pathlib import Path
import numpy as np
import pandas as pd


MARKET_ROOT_BY_CHOICE = {
    "WINFUT": "WIN",
    "WDOFUT": "WDO",
    "BOVESPA": "BOVESPA",
}


def _read_csv_flexible(path: Path, **kwargs) -> pd.DataFrame:
    last_error = None
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def br_number(value):
    """Parse Brazilian-formatted numbers without letting pandas destroy separators."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip()
    if text in {"", "-", " - ", "nan", "None"}:
        return np.nan
    text = text.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return np.nan


def find_trade_header(path: Path) -> int:
    """Profit exports start with account metadata; find the real semicolon header."""
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, line in enumerate(handle):
                    if line.startswith("Ativo;") and "Abertura" in line and "Fechamento" in line:
                        return i
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not find the trade table header in {path}")


def _root_from_ativo(ativo: str) -> str:
    a = str(ativo).strip().upper()
    if a.startswith("WIN"):
        return "WIN"
    if a.startswith("WDO"):
        return "WDO"
    # Equities like PETR4, VALE3, ITUB4...
    return "BOVESPA"


def load_trades(path: Path) -> pd.DataFrame:
    header_row = find_trade_header(path)
    df = _read_csv_flexible(path, sep=";", skiprows=header_row, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required = ["Ativo", "Abertura", "Fechamento", "Lado", "Preço Compra", "Preço Venda"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Trade file is missing columns: {missing}")

    df = df[df["Ativo"].notna()].copy()
    df["EntryDT"] = pd.to_datetime(df["Abertura"], dayfirst=True, errors="coerce")
    df["ExitDT"] = pd.to_datetime(df["Fechamento"], dayfirst=True, errors="coerce")
    df = df[df["EntryDT"].notna() & df["ExitDT"].notna()].copy()

    df["Root"] = df["Ativo"].map(_root_from_ativo)

    for col in ["Preço Compra", "Preço Venda", "Res. Operação", "Qtd Compra", "Qtd Venda", "Total"]:
        if col in df.columns:
            df[col + "_num"] = df[col].map(br_number)

    df["Side"] = df["Lado"].map({"C": "LONG", "V": "SHORT"}).fillna(df["Lado"])
    df["BuyPrice"] = df["Preço Compra_num"]
    df["SellPrice"] = df["Preço Venda_num"]
    df["EntryPrice"] = np.where(df["Lado"].eq("C"), df["BuyPrice"], df["SellPrice"])
    df["ExitPrice"] = np.where(df["Lado"].eq("C"), df["SellPrice"], df["BuyPrice"])
    df["PL"] = df.get("Res. Operação_num", np.nan)
    df["Qty"] = df[[c for c in ["Qtd Compra_num", "Qtd Venda_num"] if c in df.columns]].max(axis=1)

    raw_seconds = (df["ExitDT"] - df["EntryDT"]).dt.total_seconds().clip(lower=0)
    df["DurationSec"] = raw_seconds
    df["Duration"] = raw_seconds.map(format_duration)
    df["Date"] = df["EntryDT"].dt.date
    df["Time"] = df["EntryDT"].dt.strftime("%H:%M:%S")
    df["Outcome"] = np.select([df["PL"] > 0, df["PL"] < 0], ["Win", "Loss"], default="Flat")

    df = df.sort_values(["EntryDT", "ExitDT"]).reset_index(drop=True)

    # Stable ID so manual reviews survive replacement with a newer export.
    def make_id(row):
        key = "|".join([
            str(row["Ativo"]), row["EntryDT"].isoformat(), row["ExitDT"].isoformat(),
            str(row["Lado"]), f"{row['EntryPrice']:.6f}", f"{row['ExitPrice']:.6f}"
        ])
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]

    df["trade_id"] = df.apply(make_id, axis=1)

    # Behaviour/context fields that do not require chart data.
    df["TradeNoDay"] = df.groupby("Date").cumcount() + 1
    df["TradesDay"] = df.groupby("Date")["trade_id"].transform("count")
    df["DayPLBefore"] = df.groupby("Date")["PL"].cumsum() - df["PL"]
    df["DayPLAfter"] = df.groupby("Date")["PL"].cumsum()
    prev_exit = df.groupby("Date")["ExitDT"].shift(1)
    df["GapPrevSec"] = (df["EntryDT"] - prev_exit).dt.total_seconds()
    df["GapPrev"] = df["GapPrevSec"].map(format_gap)

    return df


def format_duration(seconds) -> str:
    if pd.isna(seconds):
        return ""
    s = int(round(float(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def format_gap(seconds) -> str:
    if pd.isna(seconds):
        return "—"
    if seconds < 0:
        return "overlap"
    return format_duration(seconds)


def load_market(path: Path, fast_ma: int = 9, slow_ma: int = 20) -> pd.DataFrame:
    df = _read_csv_flexible(path, sep=";", dtype=str)
    if len(df.columns) < 9:
        raise ValueError(f"Market file {path.name} does not look like a Profit 1-minute export.")

    # Use positions because accented Portuguese headers can vary by encoding/export version.
    df = df.iloc[:, :9].copy()
    df.columns = ["Asset", "DateText", "TimeText", "Open", "High", "Low", "Close", "Volume", "Quantity"]
    df["DateTime"] = pd.to_datetime(df["DateText"] + " " + df["TimeText"], dayfirst=True, errors="coerce")
    df = df[df["DateTime"].notna()].copy()

    for col in ["Open", "High", "Low", "Close", "Volume", "Quantity"]:
        df[col] = df[col].map(br_number)

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).sort_values("DateTime").reset_index(drop=True)
    df["SessionDate"] = df["DateTime"].dt.date

    # MAs are calculated on the full chronological series, like a normal intraday chart.
    df["MA9"] = df["Close"].rolling(fast_ma, min_periods=1).mean()
    df["MA20"] = df["Close"].rolling(slow_ma, min_periods=1).mean()

    # These are rolling, not final-day hindsight levels.
    df["DayHighKnown"] = df.groupby("SessionDate")["High"].cummax()
    df["DayLowKnown"] = df.groupby("SessionDate")["Low"].cummin()

    daily = df.groupby("SessionDate").agg(SessionHigh=("High", "max"), SessionLow=("Low", "min")).reset_index()
    daily["PrevHigh"] = daily["SessionHigh"].shift(1)
    daily["PrevLow"] = daily["SessionLow"].shift(1)
    df = df.merge(daily[["SessionDate", "PrevHigh", "PrevLow"]], on="SessionDate", how="left")
    return df


def load_all(
    trades_file: Path,
    market_choice: str,
    market_file: Path,
    fast_ma=9,
    slow_ma=20,
):
    if market_choice not in MARKET_ROOT_BY_CHOICE:
        raise ValueError(f"Unknown market choice: {market_choice}")

    selected_root = MARKET_ROOT_BY_CHOICE[market_choice]
    trades = load_trades(trades_file)
    trades = trades[trades["Root"] == selected_root].copy().reset_index(drop=True)

    if trades.empty:
        raise ValueError(
            f"No {market_choice} trades found in {trades_file.name}. "
            f"Check selected market type and trade file contents."
        )

    market_df = load_market(market_file, fast_ma, slow_ma)

    # For BOVESPA, try to keep only the selected symbol if identifiable.
    if selected_root == "BOVESPA":
        unique_assets = (
            market_df["Asset"]
            .astype(str)
            .str.strip()
            .replace({"": np.nan})
            .dropna()
            .str.upper()
            .unique()
            .tolist()
        )
        if len(unique_assets) == 1:
            asset = unique_assets[0]
            trades = trades[trades["Ativo"].astype(str).str.upper() == asset].copy().reset_index(drop=True)
            if trades.empty:
                raise ValueError(
                    f"The selected BOVESPA file appears to be for {asset}, "
                    f"but no matching trades were found in {trades_file.name}."
                )

    markets = {selected_root: market_df}
    return trades, markets