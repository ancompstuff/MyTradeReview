from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd


MARKET_ROOT_BY_CHOICE = {
    "WINFUT": "WIN",
    "WDOFUT": "WDO",
    "BOVESPA": "BOVESPA",
}

# R$ per 1.0 price point, per contract
POINT_VALUE = {
    "WIN": 0.2,
    "WDO": 10.0,
    "BOVESPA": 1.0,  # placeholder; basic format already provides PL for equities
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
    """Find first semicolon header used by basic Profit operations export."""
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, line in enumerate(handle):
                    if line.startswith("Ativo;") and "Abertura" in line and "Fechamento" in line:
                        return i
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not find the basic trade table header in {path}")


def _first_semicolon_header_line(path: Path) -> tuple[int, str]:
    """Return (line_index, header_text) for the first likely semicolon CSV header."""
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, raw in enumerate(handle):
                    line = raw.strip()
                    if line.count(";") >= 5:
                        return i, line
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not find semicolon header in {path}")


def _root_from_ativo(ativo: str) -> str:
    a = str(ativo).strip().upper()
    if a.startswith("WIN"):
        return "WIN"
    if a.startswith("WDO"):
        return "WDO"
    return "BOVESPA"


def detect_trade_format(path: Path) -> str:
    """
    Detect supported trade format:
      - 'basic': Ativo/Abertura/Fechamento...
      - 'all_operations': Corretora/ClOrdID/Status/Criação...
    """
    _, header = _first_semicolon_header_line(path)
    cols = [c.strip() for c in header.split(";")]

    basic_markers = {"Ativo", "Abertura", "Fechamento", "Lado", "Preço Compra", "Preço Venda"}
    all_ops_markers = {"Corretora", "ClOrdID", "Status", "Criação", "Última Atualização", "Origem"}

    colset = set(cols)
    if basic_markers.issubset(colset):
        return "basic"
    if all_ops_markers.issubset(colset):
        return "all_operations"

    raise ValueError(
        f"Unsupported trade file format: {path.name}. "
        f"Header columns found: {cols[:12]}"
    )


def _finalize_trades_df(df: pd.DataFrame) -> pd.DataFrame:
    raw_seconds = (df["ExitDT"] - df["EntryDT"]).dt.total_seconds().clip(lower=0)
    df["DurationSec"] = raw_seconds
    df["Duration"] = raw_seconds.map(format_duration)
    df["Date"] = df["EntryDT"].dt.date
    df["Time"] = df["EntryDT"].dt.strftime("%H:%M:%S")
    df["Outcome"] = np.select([df["PL"] > 0, df["PL"] < 0], ["Win", "Loss"], default="Flat")

    df = df.sort_values(["EntryDT", "ExitDT"]).reset_index(drop=True)

    # Stable ID with row-seq suffix to prevent duplicate iids in Treeview
    def make_id(row):
        key = "|".join([
            str(row["Ativo"]),
            row["EntryDT"].isoformat(),
            row["ExitDT"].isoformat(),
            str(row.get("Lado", "")),
            f"{float(row['EntryPrice']):.6f}",
            f"{float(row['ExitPrice']):.6f}",
        ])
        base = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
        return f"{base}_{int(row['_seq'])}"

    df["_seq"] = np.arange(len(df), dtype=int)
    df["trade_id"] = df.apply(make_id, axis=1)
    df = df.drop(columns=["_seq"])

    # Behaviour/context fields used elsewhere
    df["TradeNoDay"] = df.groupby("Date").cumcount() + 1
    df["TradesDay"] = df.groupby("Date")["trade_id"].transform("count")
    df["DayPLBefore"] = df.groupby("Date")["PL"].cumsum() - df["PL"]
    df["DayPLAfter"] = df.groupby("Date")["PL"].cumsum()
    prev_exit = df.groupby("Date")["ExitDT"].shift(1)
    df["GapPrevSec"] = (df["EntryDT"] - prev_exit).dt.total_seconds()
    df["GapPrev"] = df["GapPrevSec"].map(format_gap)

    return df


def _load_trades_basic(path: Path) -> pd.DataFrame:
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

    return _finalize_trades_df(df)


def _parse_qty(value, default=1) -> int:
    n = br_number(value)
    if pd.isna(n):
        return default
    return max(1, int(round(float(n))))


def _parse_dt(value):
    return pd.to_datetime(str(value).strip(), dayfirst=True, errors="coerce")


def _pl_for_close(root: str, side_open: str, entry_price: float, exit_price: float, qty: int = 1) -> float:
    mult = POINT_VALUE.get(root, 1.0)
    if side_open == "LONG":
        pts = exit_price - entry_price
    else:
        pts = entry_price - exit_price
    return float(pts * mult * qty)


def _load_trades_all_operations(path: Path) -> pd.DataFrame:
    header_row, _ = _first_semicolon_header_line(path)
    raw = _read_csv_flexible(path, sep=";", skiprows=header_row, dtype=str)
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw.fillna("")

    required = ["Ativo", "Lado", "Status", "Criação", "Última Atualização", "ClOrdID", "Preço Médio", "Qtd", "Qtd Executada"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"Detailed all_operations file missing columns: {missing}")

    for c in ["Ativo", "Lado", "Status", "ClOrdID"]:
        raw[c] = raw[c].astype(str).str.strip()

    raw["CreateDT"] = raw["Criação"].map(_parse_dt)
    raw["UpdateDT"] = raw["Última Atualização"].map(_parse_dt)
    raw["PrecoMedio_num"] = raw["Preço Médio"].map(br_number)

    # ---- 1) Build ORDERS: each "Executada" row + its immediate "Trade" child rows (fills) ----
    orders = []
    i, n = 0, len(raw)
    while i < n:
        row = raw.iloc[i]
        if row["Status"] == "Executada" and row["Ativo"]:
            ativo = row["Ativo"]
            lado = row["Lado"].upper()  # C / V
            clordid = row["ClOrdID"] or f"row_{i}"
            parent_dt = row["UpdateDT"] if pd.notna(row["UpdateDT"]) else row["CreateDT"]
            parent_px = row["PrecoMedio_num"]
            parent_q = _parse_qty(row["Qtd Executada"], default=_parse_qty(row["Qtd"], default=1))

            fills = []  # one (datetime, price) per contract
            j = i + 1
            while j < n and raw.iloc[j]["Status"] == "Trade":
                tr = raw.iloc[j]
                tdt = tr["CreateDT"] if pd.notna(tr["CreateDT"]) else parent_dt
                tpx = tr["PrecoMedio_num"] if pd.notna(tr["PrecoMedio_num"]) else parent_px
                tq = _parse_qty(tr["Qtd Executada"], default=1)
                if pd.notna(tdt) and pd.notna(tpx):
                    fills.extend([(tdt, float(tpx))] * tq)
                j += 1

            if not fills and pd.notna(parent_dt) and pd.notna(parent_px):
                fills = [(parent_dt, float(parent_px))] * parent_q

            if fills:
                fills.sort(key=lambda f: f[0])
                orders.append({
                    "id": clordid, "ativo": ativo, "root": _root_from_ativo(ativo),
                    "lado": lado, "fills": fills, "first_dt": fills[0][0],
                })
            i = j
        else:
            i += 1

    if not orders:
        raise ValueError("No executed orders parsed from all_operations file.")

    orders.sort(key=lambda o: (o["first_dt"], o["id"]))

    # ---- 2) FIFO match. Entry lot = whole entry order (one time, one avg price).
    #         Each contract exits on its own fill. ----
    long_lots = defaultdict(deque)   # opened by C, closed by V
    short_lots = defaultdict(deque)  # opened by V, closed by C
    trades = []

    for o in orders:
        root, lado = o["root"], o["lado"]
        if lado == "C":
            closing_lots, opening_lots = short_lots[root], long_lots[root]
            closed_side, closed_lado = "SHORT", "V"
        elif lado == "V":
            closing_lots, opening_lots = long_lots[root], short_lots[root]
            closed_side, closed_lado = "LONG", "C"
        else:
            continue

        opening_fills = []
        for fdt, fpx in o["fills"]:
            if closing_lots:
                lot = closing_lots[0]
                trades.append({
                    "Ativo": lot["ativo"],
                    "Root": root,
                    "Lado": closed_lado,
                    "Side": closed_side,
                    "EntryDT": lot["dt"],
                    "ExitDT": fdt,
                    "EntryPrice": lot["price"],
                    "ExitPrice": fpx,
                    "Qty": 1.0,
                    "PL": _pl_for_close(root, closed_side, lot["price"], fpx, 1),
                    "PositionId": lot["id"],
                    "PositionQty": lot["qty"],
                })
                lot["remaining"] -= 1
                if lot["remaining"] == 0:
                    closing_lots.popleft()
            else:
                opening_fills.append((fdt, fpx))

        if opening_fills:
            opening_lots.append({
                "id": o["id"],
                "ativo": o["ativo"],
                "dt": opening_fills[0][0],                                   # entry time = first fill of the order
                "price": float(np.mean([p for _, p in opening_fills])),      # avg entry price of the order
                "qty": len(opening_fills),
                "remaining": len(opening_fills),
            })

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        raise ValueError(
            "No closed trades could be matched from all_operations file. "
            "You may have only entries or only exits in the selected date range."
        )

    return _finalize_trades_df(trades_df)

def load_trades(path: Path) -> pd.DataFrame:
    fmt = detect_trade_format(path)
    if fmt == "basic":
        return _load_trades_basic(path)
    if fmt == "all_operations":
        return _load_trades_all_operations(path)
    raise ValueError(f"Unsupported trade format: {fmt}")


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

    return add_market_indicators(df, fast_ma, slow_ma)


def add_market_indicators(df: pd.DataFrame, fast_ma: int = 9, slow_ma: int = 20) -> pd.DataFrame:
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).sort_values("DateTime").reset_index(drop=True)
    df["SessionDate"] = df["DateTime"].dt.date

    df["MA9"] = df["Close"].rolling(fast_ma, min_periods=1).mean()
    df["MA20"] = df["Close"].rolling(slow_ma, min_periods=1).mean()

    df["DayHighKnown"] = df.groupby("SessionDate")["High"].cummax()
    df["DayLowKnown"] = df.groupby("SessionDate")["Low"].cummin()

    daily = df.groupby("SessionDate").agg(SessionHigh=("High", "max"), SessionLow=("Low", "min")).reset_index()
    daily["PrevHigh"] = daily["SessionHigh"].shift(1)
    daily["PrevLow"] = daily["SessionLow"].shift(1)

    return df.merge(daily[["SessionDate", "PrevHigh", "PrevLow"]], on="SessionDate", how="left")


def load_all(
    trades_file: Path,
    market_choice: str,
    market_file: Path | None = None,
    fast_ma=9,
    slow_ma=20,
    market_df: pd.DataFrame | None = None,
):
    if market_choice not in MARKET_ROOT_BY_CHOICE:
        raise ValueError(f"Unknown market choice: {market_choice}")

    selected_root = MARKET_ROOT_BY_CHOICE[market_choice]
    trades = load_trades(trades_file)
    trades = trades[trades["Root"] == selected_root].copy().reset_index(drop=True)

    if trades.empty:
        raise ValueError(
            f"No {market_choice} trades found in {trades_file.name}. "
            f"Check the selected market type and the trade file contents."
        )

    # Tick mode passes market_df already built; minute mode reads CSV.
    if market_df is None:
        if market_file is None:
            raise ValueError("No market data was provided.")
        market_df = load_market(market_file, fast_ma, slow_ma)

    # For BOVESPA, keep only symbol present in market data, if unique.
    if selected_root == "BOVESPA" and "Asset" in market_df.columns:
        unique_assets = (
            market_df["Asset"].astype(str).str.strip().str.upper()
            .replace({"": np.nan, "NAN": np.nan}).dropna().unique().tolist()
        )
        if len(unique_assets) == 1:
            asset = unique_assets[0]
            trades = trades[trades["Ativo"].astype(str).str.upper() == asset].copy().reset_index(drop=True)
            if trades.empty:
                raise ValueError(
                    f"The data file appears to be for {asset}, "
                    f"but no matching trades were found in {trades_file.name}."
                )

    return trades, {selected_root: market_df}