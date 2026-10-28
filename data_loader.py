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
POINT_VALUE = {"WIN": 0.2, "WDO": 10.0, "BOVESPA": 1.0}

# Positional names for first columns of the all_operations export
ALL_OPS_COLUMNS = [
    "Corretora", "Conta", "Titular", "ClOrdID", "Ativo", "Lado", "Status",
    "Criacao", "UltimaAtualizacao", "Preco", "PrecoStop", "Qtd", "PrecoMedio", "QtdExecutada"
]


def _read_csv_flexible(path: Path, **kwargs) -> pd.DataFrame:
    last_error = None
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def br_number(value):
    """Parse Brazilian-formatted numbers."""
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


def _parse_dt(value):
    """Keep milliseconds if present."""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return pd.NaT
    for fmt in ("%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S"):
        try:
            return pd.to_datetime(text, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.to_datetime(text, dayfirst=True, errors="coerce")


def _find_header_line(path: Path, starts_with: str) -> int | None:
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, line in enumerate(handle):
                    if line.startswith(starts_with):
                        return i
            return None
        except UnicodeDecodeError:
            continue
    return None


def find_trade_header(path: Path) -> int:
    """Basic Profit export header."""
    for encoding in ("cp1252", "latin1", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                for i, line in enumerate(handle):
                    if line.startswith("Ativo;") and "Abertura" in line and "Fechamento" in line:
                        return i
            break
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not find the basic trade table header in {path}")


def detect_trade_format(path: Path) -> str:
    if _find_header_line(path, "Corretora;") is not None:
        return "all_operations"
    if _find_header_line(path, "Ativo;") is not None:
        return "basic"
    raise ValueError(
        f"Unsupported trades file: {path.name}. "
        f"Expected 'Ativo;' (basic) or 'Corretora;' (all operations)."
    )


def _root_from_ativo(ativo: str) -> str:
    a = str(ativo).strip().upper()
    if a.startswith("WIN"):
        return "WIN"
    if a.startswith("WDO"):
        return "WDO"
    return "BOVESPA"


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


def _finalize_trades_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "PositionId" not in df.columns:
        df["PositionId"] = pd.NA
    if "PositionQty" not in df.columns:
        df["PositionQty"] = df["Qty"]

    df["_pos_key"] = df["PositionId"].where(
        df["PositionId"].notna(),
        pd.Series(range(len(df)), index=df.index).astype(str)
    )
    df = df.sort_values(["EntryDT", "_pos_key", "ExitDT"]).reset_index(drop=True)
    df["LegNo"] = df.groupby("_pos_key").cumcount() + 1
    df["GroupNo"] = df.groupby("_pos_key", sort=False).ngroup()

    raw_seconds = (df["ExitDT"] - df["EntryDT"]).dt.total_seconds().clip(lower=0)
    df["DurationSec"] = raw_seconds
    df["Duration"] = raw_seconds.map(format_duration)
    df["Date"] = df["EntryDT"].dt.date
    df["Time"] = df["EntryDT"].dt.strftime("%H:%M:%S")
    df["Outcome"] = np.select([df["PL"] > 0, df["PL"] < 0], ["Win", "Loss"], default="Flat")

    def make_id(row):
        key = "|".join([
            str(row["Ativo"]),
            row["EntryDT"].isoformat(),
            row["ExitDT"].isoformat(),
            str(row["Lado"]),
            f"{float(row['EntryPrice']):.6f}",
            f"{float(row['ExitPrice']):.6f}",
            str(row["_pos_key"]),
            str(row["LegNo"]),
        ])
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]

    df["trade_id"] = df.apply(make_id, axis=1)
    df["PositionId"] = df["_pos_key"]
    df = df.drop(columns=["_pos_key"])

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
    df["EntryDT"] = df["Abertura"].map(_parse_dt)
    df["ExitDT"] = df["Fechamento"].map(_parse_dt)
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
    df["PositionId"] = pd.NA
    df["PositionQty"] = df["Qty"]
    return _finalize_trades_df(df)


def _pl_points(root: str, side: str, entry: float, exit_: float) -> float:
    pts = (exit_ - entry) if side == "LONG" else (entry - exit_)
    return float(pts * POINT_VALUE.get(root, 1.0))


def _qty(value, default=1) -> int:
    n = br_number(value)
    return default if pd.isna(n) else max(1, int(round(float(n))))


def _load_trades_all_operations(path: Path) -> pd.DataFrame:
    header_row = _find_header_line(path, "Corretora;")
    raw = _read_csv_flexible(path, sep=";", skiprows=header_row, dtype=str, header=0)
    if raw.shape[1] < len(ALL_OPS_COLUMNS):
        raise ValueError("All-operations file has fewer columns than expected.")

    names = list(raw.columns)
    names[:len(ALL_OPS_COLUMNS)] = ALL_OPS_COLUMNS
    raw.columns = names
    raw = raw.fillna("")

    for c in ("ClOrdID", "Ativo", "Lado", "Status"):
        raw[c] = raw[c].astype(str).str.strip()

    # 1) Build orders (parent Executada + child Trade fills)
    orders = []
    i, n = 0, len(raw)
    while i < n:
        row = raw.iloc[i]
        status = row["Status"]
        if "xecut" in status and row["Ativo"]:
            ativo = row["Ativo"]
            lado = row["Lado"].upper()
            parent_dt = _parse_dt(row["UltimaAtualizacao"])
            if pd.isna(parent_dt):
                parent_dt = _parse_dt(row["Criacao"])
            parent_px = br_number(row["PrecoMedio"])
            parent_q = _qty(row["QtdExecutada"], default=_qty(row["Qtd"]))

            fills = []
            j = i + 1
            while j < n and raw.iloc[j]["Status"] == "Trade":
                tr = raw.iloc[j]
                tdt = _parse_dt(tr["Criacao"])
                if pd.isna(tdt):
                    tdt = parent_dt
                tpx = br_number(tr["PrecoMedio"])
                if pd.isna(tpx):
                    tpx = parent_px
                tq = _qty(tr["QtdExecutada"], default=1)
                if pd.notna(tdt) and pd.notna(tpx):
                    fills.extend([(tdt, float(tpx))] * tq)
                j += 1

            if not fills and pd.notna(parent_dt) and pd.notna(parent_px):
                fills = [(parent_dt, float(parent_px))] * parent_q

            if fills and lado in ("C", "V"):
                fills.sort(key=lambda f: f[0])
                orders.append({
                    "id": row["ClOrdID"] or f"row_{i}",
                    "ativo": ativo,
                    "root": _root_from_ativo(ativo),
                    "lado": lado,
                    "fills": fills,
                    "first_dt": fills[0][0],
                })
            i = j
        else:
            i += 1

    if not orders:
        raise ValueError("No executed orders found in the all-operations file.")
    orders.sort(key=lambda o: (o["first_dt"], o["id"]))

    # 2) FIFO matching PER EXACT CONTRACT (Ativo)
    long_lots = defaultdict(deque)     # opened by C, closed by V
    short_lots = defaultdict(deque)    # opened by V, closed by C
    rows = []

    for o in orders:
        ativo, root = o["ativo"], o["root"]
        if o["lado"] == "C":
            closing, opening = short_lots[ativo], long_lots[ativo]
            closed_side, closed_lado = "SHORT", "V"
        else:
            closing, opening = long_lots[ativo], short_lots[ativo]
            closed_side, closed_lado = "LONG", "C"

        opening_fills = []
        for fdt, fpx in o["fills"]:
            if closing:
                lot = closing[0]
                rows.append({
                    "Ativo": ativo,
                    "Root": root,
                    "Lado": closed_lado,
                    "Side": closed_side,
                    "EntryDT": lot["dt"],
                    "ExitDT": fdt,
                    "EntryPrice": lot["price"],
                    "ExitPrice": fpx,
                    "Qty": 1.0,
                    "PL": _pl_points(root, closed_side, lot["price"], fpx),
                    "PositionId": lot["id"],
                    "PositionQty": lot["qty"],
                })
                lot["remaining"] -= 1
                if lot["remaining"] == 0:
                    closing.popleft()
            else:
                opening_fills.append((fdt, fpx))

        if opening_fills:
            opening.append({
                "id": o["id"],
                "dt": opening_fills[0][0],                              # one entry time per order (first fill)
                "price": float(np.mean([p for _, p in opening_fills])), # avg entry price
                "qty": len(opening_fills),
                "remaining": len(opening_fills),
            })

    if not rows:
        raise ValueError("No closed trades matched in all-operations file.")
    return _finalize_trades_df(pd.DataFrame(rows))


def load_trades(path: Path) -> pd.DataFrame:
    fmt = detect_trade_format(path)
    if fmt == "all_operations":
        return _load_trades_all_operations(path)
    return _load_trades_basic(path)


def load_market(path: Path, fast_ma: int = 9, slow_ma: int = 20) -> pd.DataFrame:
    df = _read_csv_flexible(path, sep=";", dtype=str)
    if len(df.columns) < 9:
        raise ValueError(f"Market file {path.name} does not look like a Profit 1-minute export.")

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
            f"Check selected market type and trade file."
        )

    if market_df is None:
        if market_file is None:
            raise ValueError("No market data was provided.")
        market_df = load_market(market_file, fast_ma, slow_ma)

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
                    f"Data file appears to be for {asset}, but no matching trades were found in {trades_file.name}."
                )

    return trades, {selected_root: market_df}