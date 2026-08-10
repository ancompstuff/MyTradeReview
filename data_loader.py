from __future__ import annotations

import hashlib
from pathlib import Path
import numpy as np
import pandas as pd


def _read_csv_flexible(path: Path, **kwargs) -> pd.DataFrame:
    last_error = None
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def br_number(value):
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
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, line in enumerate(handle):
                    if line.startswith("Ativo;") and "Abertura" in line and "Fechamento" in line:
                        return i
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not find the trade table header in {path}")


def make_trade_id(row) -> str:
    key = "|".join([
        str(row["Ativo"]), pd.Timestamp(row["EntryDT"]).isoformat(), pd.Timestamp(row["ExitDT"]).isoformat(),
        str(row["Lado"]), f"{float(row['EntryPrice']):.6f}", f"{float(row['ExitPrice']):.6f}"
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def load_trades(path: Path) -> pd.DataFrame:
    """Read a Profit operations export and return normalized completed WIN/WDO trades."""
    header_row = find_trade_header(path)
    df = _read_csv_flexible(path, sep=";", skiprows=header_row, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required = ["Ativo", "Abertura", "Fechamento", "Lado", "Preço Compra", "Preço Venda"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Trade file is missing columns: {missing}")

    df = df.loc[df["Ativo"].notna()].copy()
    df.loc[:, "EntryDT"] = pd.to_datetime(df["Abertura"], dayfirst=True, errors="coerce")
    df.loc[:, "ExitDT"] = pd.to_datetime(df["Fechamento"], dayfirst=True, errors="coerce")
    df = df.loc[df["EntryDT"].notna() & df["ExitDT"].notna()].copy()

    df.loc[:, "Root"] = df["Ativo"].str.extract(r"^(WIN|WDO)", expand=False)
    df = df.loc[df["Root"].isin(["WIN", "WDO"])].copy()

    for col in ["Preço Compra", "Preço Venda", "Res. Operação", "Qtd Compra", "Qtd Venda", "Total"]:
        if col in df.columns:
            df.loc[:, col + "_num"] = df[col].map(br_number)

    df.loc[:, "Side"] = df["Lado"].map({"C": "LONG", "V": "SHORT"}).fillna(df["Lado"])
    df.loc[:, "BuyPrice"] = df["Preço Compra_num"]
    df.loc[:, "SellPrice"] = df["Preço Venda_num"]
    df.loc[:, "EntryPrice"] = np.where(df["Lado"].eq("C"), df["BuyPrice"], df["SellPrice"])
    df.loc[:, "ExitPrice"] = np.where(df["Lado"].eq("C"), df["SellPrice"], df["BuyPrice"])
    df.loc[:, "PL"] = df["Res. Operação_num"] if "Res. Operação_num" in df.columns else np.nan
    qty_cols = [c for c in ["Qtd Compra_num", "Qtd Venda_num"] if c in df.columns]
    df.loc[:, "Qty"] = df[qty_cols].max(axis=1) if qty_cols else np.nan

    # Master-journal columns only. Context fields are recalculated after merging imports.
    keep = ["Ativo", "Lado", "EntryDT", "ExitDT", "Root", "Side", "BuyPrice", "SellPrice",
            "EntryPrice", "ExitPrice", "PL", "Qty"]
    result = df[keep].copy()
    result.loc[:, "trade_id"] = result.apply(make_trade_id, axis=1)
    return finalize_trades(result)


def finalize_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Recalculate order/day context after old and new trade imports are merged."""
    if df.empty:
        return df.copy()
    out = df.copy()
    out["EntryDT"] = pd.to_datetime(out["EntryDT"], errors="coerce")
    out["ExitDT"] = pd.to_datetime(out["ExitDT"], errors="coerce")
    for c in ["EntryPrice", "ExitPrice", "PL", "Qty", "BuyPrice", "SellPrice"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.loc[out["EntryDT"].notna() & out["ExitDT"].notna()].copy()
    out = out.sort_values(["EntryDT", "ExitDT", "trade_id"]).drop_duplicates("trade_id", keep="last").reset_index(drop=True)

    raw_seconds = (out["ExitDT"] - out["EntryDT"]).dt.total_seconds().clip(lower=0)
    out.loc[:, "DurationSec"] = raw_seconds
    out.loc[:, "Duration"] = raw_seconds.map(format_duration)
    out.loc[:, "Date"] = out["EntryDT"].dt.date
    out.loc[:, "Time"] = out["EntryDT"].dt.strftime("%H:%M:%S")
    out.loc[:, "Outcome"] = np.select([out["PL"] > 0, out["PL"] < 0], ["Win", "Loss"], default="Flat")
    out.loc[:, "TradeNoDay"] = out.groupby("Date").cumcount() + 1
    out.loc[:, "TradesDay"] = out.groupby("Date")["trade_id"].transform("count")
    out.loc[:, "DayPLBefore"] = out.groupby("Date")["PL"].cumsum() - out["PL"]
    out.loc[:, "DayPLAfter"] = out.groupby("Date")["PL"].cumsum()
    prev_exit = out.groupby("Date")["ExitDT"].shift(1)
    out.loc[:, "GapPrevSec"] = (out["EntryDT"] - prev_exit).dt.total_seconds()
    out.loc[:, "GapPrev"] = out["GapPrevSec"].map(format_gap)
    return out


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


def load_market_base(path: Path) -> pd.DataFrame:
    """Read a Profit 1-minute export, without indicators, suitable for master-store merging."""
    df = _read_csv_flexible(path, sep=";", dtype=str)
    if len(df.columns) < 9:
        raise ValueError(f"Market file {path.name} does not look like a Profit 1-minute export.")
    df = df.iloc[:, :9].copy()
    df.columns = ["Asset", "DateText", "TimeText", "Open", "High", "Low", "Close", "Volume", "Quantity"]
    df.loc[:, "DateTime"] = pd.to_datetime(df["DateText"] + " " + df["TimeText"], dayfirst=True, errors="coerce")
    df = df.loc[df["DateTime"].notna()].copy()
    for col in ["Open", "High", "Low", "Close", "Volume", "Quantity"]:
        df.loc[:, col] = df[col].map(br_number)
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).sort_values("DateTime")
    df = df.drop_duplicates("DateTime", keep="last").reset_index(drop=True)
    return df[["Asset", "DateTime", "Open", "High", "Low", "Close", "Volume", "Quantity"]]


def derive_market(df: pd.DataFrame, fast_ma: int = 9, slow_ma: int = 20, long_ma: int = 80) -> pd.DataFrame:
    """Add indicators/context to the master 1-minute series."""
    out = df.copy()
    out["DateTime"] = pd.to_datetime(out["DateTime"], errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume", "Quantity"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["DateTime", "Open", "High", "Low", "Close"]).sort_values("DateTime")
    out = out.drop_duplicates("DateTime", keep="last").reset_index(drop=True)
    out.loc[:, "SessionDate"] = out["DateTime"].dt.date

    # Moving averages run through the chronological 1-minute series.
    out.loc[:, "MA9"] = out["Close"].rolling(fast_ma, min_periods=1).mean()
    out.loc[:, "MA20"] = out["Close"].rolling(slow_ma, min_periods=1).mean()
    out.loc[:, "MA80"] = out["Close"].rolling(long_ma, min_periods=1).mean()

    # Session VWAP resets every trading day and only uses information known up to each bar.
    typical = (out["High"] + out["Low"] + out["Close"]) / 3.0
    weight = out["Quantity"].fillna(0).clip(lower=0)
    pv = typical * weight
    cum_w = weight.groupby(out["SessionDate"]).cumsum()
    cum_pv = pv.groupby(out["SessionDate"]).cumsum()
    out.loc[:, "VWAP"] = cum_pv.div(cum_w.replace(0, np.nan)).groupby(out["SessionDate"]).ffill()

    out.loc[:, "DayHighKnown"] = out.groupby("SessionDate")["High"].cummax()
    out.loc[:, "DayLowKnown"] = out.groupby("SessionDate")["Low"].cummin()
    daily = out.groupby("SessionDate").agg(SessionHigh=("High", "max"), SessionLow=("Low", "min")).reset_index()
    daily.loc[:, "PrevHigh"] = daily["SessionHigh"].shift(1)
    daily.loc[:, "PrevLow"] = daily["SessionLow"].shift(1)
    out = out.merge(daily[["SessionDate", "PrevHigh", "PrevLow"]], on="SessionDate", how="left")
    return out


def load_market(path: Path, fast_ma: int = 9, slow_ma: int = 20) -> pd.DataFrame:
    return derive_market(load_market_base(path), fast_ma, slow_ma)


def load_all(trades_file: Path, win_file: Path, wdo_file: Path, fast_ma=9, slow_ma=20):
    trades = load_trades(trades_file)
    markets = {
        "WIN": load_market(win_file, fast_ma, slow_ma),
        "WDO": load_market(wdo_file, fast_ma, slow_ma),
    }
    return trades, markets
