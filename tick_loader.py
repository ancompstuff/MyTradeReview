from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import config


def _q(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _cache_path(csv_path: Path) -> Path:
    st = csv_path.stat()
    key = f"{csv_path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return config.TICK_CACHE_DIR / f"{csv_path.stem}_{h}.parquet"


def ensure_parquet(csv_path: Path) -> Path:
    """Convert the big tick CSV to a cached Parquet file (first time only)."""
    out = _cache_path(csv_path)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        tmp.unlink()

    con = duckdb.connect()
    try:
        con.execute(f"""
            COPY (
                SELECT asset, ts, buyer, seller, price, qty, aggressor, seq
                FROM (
                    SELECT asset,
                           try_strptime(d || ' ' || t, '%d/%m/%Y %H:%M:%S') AS ts,
                           buyer, seller,
                           try_cast(replace(replace(trim(price_txt), '.', ''), ',', '.') AS DOUBLE) AS price,
                           try_cast(trim(qty_txt) AS INTEGER) AS qty,
                           aggressor,
                           row_number() OVER () AS seq
                    FROM read_csv(
                        '{_q(csv_path)}',
                        delim=';', header=false, encoding='{config.TICK_ENCODING}',
                        ignore_errors=true, all_varchar=true,
                        columns={{
                            'asset': 'VARCHAR', 'd': 'VARCHAR', 't': 'VARCHAR',
                            'buyer': 'VARCHAR', 'price_txt': 'VARCHAR', 'qty_txt': 'VARCHAR',
                            'seller': 'VARCHAR', 'aggressor': 'VARCHAR'
                        }}
                    )
                )
                WHERE ts IS NOT NULL AND price IS NOT NULL AND qty IS NOT NULL
                ORDER BY ts, seq
            ) TO '{_q(tmp)}' (FORMAT PARQUET)
        """)
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{_q(tmp)}')").fetchone()[0]
    finally:
        con.close()

    if rows == 0:
        tmp.unlink(missing_ok=True)
        raise ValueError("No ticks could be read. Check the file format and encoding (TICK_ENCODING in config.py).")
    tmp.replace(out)
    return out


def minute_bars(parquet: Path) -> pd.DataFrame:
    """1-minute OHLC bars for the whole file (same columns as the Profit minute loader)."""
    con = duckdb.connect()
    try:
        df = con.execute(f"""
            SELECT any_value(asset) AS Asset,
                   date_trunc('minute', ts) AS DateTime,
                   first(price ORDER BY ts, seq) AS Open,
                   max(price) AS High,
                   min(price) AS Low,
                   last(price ORDER BY ts, seq) AS Close,
                   sum(price * qty) AS Volume,
                   sum(qty) AS Quantity
            FROM read_parquet('{_q(parquet)}')
            GROUP BY DateTime
            ORDER BY DateTime
        """).df()
    finally:
        con.close()
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    return df


def _load_bars(parquet: Path, t0: pd.Timestamp, t1: pd.Timestamp, bar_sec: int) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        df = con.execute(f"""
            SELECT time_bucket(INTERVAL '{int(bar_sec)} seconds', ts) AS DateTime,
                   first(price ORDER BY ts, seq) AS Open,
                   max(price) AS High,
                   min(price) AS Low,
                   last(price ORDER BY ts, seq) AS Close,
                   sum(qty) AS Qty,
                                       sum(CASE
                            WHEN lower(trim(aggressor)) IN ('comprador', 'buy')
                            THEN qty ELSE 0
                        END) AS BuyVol,
                    sum(CASE
                            WHEN lower(trim(aggressor)) IN ('vendedor', 'sell')
                            THEN qty ELSE 0
                        END) AS SellVol,
                    sum(CASE
                            WHEN lower(trim(aggressor)) IN ('rlp', 'leilão', 'leilao')
                                 OR COALESCE(trim(aggressor), '') = ''
                            THEN qty ELSE 0
                        END) AS OtherVol,
                   count(*) AS Ticks
            FROM read_parquet('{_q(parquet)}')
            WHERE ts >= ? AND ts < ?
            GROUP BY 1
            ORDER BY 1
        """, [t0.to_pydatetime(), t1.to_pydatetime()]).df()
    finally:
        con.close()
    if df.empty:
        return df

    df["DateTime"] = pd.to_datetime(df["DateTime"])
    idx = pd.date_range(t0, t1, freq=f"{int(bar_sec)}s", inclusive="left")
    df = df.set_index("DateTime").reindex(idx)
    df.index.name = "DateTime"
    df["Close"] = df["Close"].ffill().bfill()
    for c in ("Open", "High", "Low"):
        df[c] = df[c].fillna(df["Close"])
    for c in ("Qty", "BuyVol", "SellVol", "OtherVol", "Ticks"):
        df[c] = df[c].fillna(0)
    return df.reset_index()


def _cum_delta_before(parquet: Path, t0: pd.Timestamp) -> float:
    day_start = t0.normalize()
    con = duckdb.connect()
    try:
        r = con.execute(f"""
            SELECT COALESCE(sum(CASE WHEN aggressor = 'Comprador' THEN qty
                                     WHEN aggressor = 'Vendedor'  THEN -qty
                                     ELSE 0 END), 0)
            FROM read_parquet('{_q(parquet)}')
            WHERE ts >= ? AND ts < ?
        """, [day_start.to_pydatetime(), t0.to_pydatetime()]).fetchone()[0]
    finally:
        con.close()
    return float(r or 0)


def _absorption(b: pd.DataFrame, n: int, max_move: float):
    sell = b["SellVol"].rolling(n, min_periods=n).sum()
    buy = b["BuyVol"].rolling(n, min_periods=n).sum()
    move = b["Close"] - b["Close"].shift(n)
    flat = move.abs() <= max_move
    q, dom = config.ABS_VOL_QUANTILE, config.ABS_DOMINANCE
    bull = flat & (sell >= sell.quantile(q)) & (sell > dom * buy)   # selling absorbed
    bear = flat & (buy >= buy.quantile(q)) & (buy > dom * sell)     # buying absorbed
    return bull, bear


def _cover(flag: pd.Series, n: int) -> np.ndarray:
    """A flag at bar i means bars i-n+1..i are involved; mark all of them."""
    f = flag.astype(float)[::-1].rolling(n, min_periods=1).max()[::-1]
    return f.astype(bool).values


def prepare_scalp_bars(parquet: Path, trade: pd.Series, tick_size: float):
    """Returns (bars_with_flow_and_flags, view_start, view_end)."""
    bar = int(config.SCALP_BAR_SEC)
    entry = pd.Timestamp(trade["EntryDT"])
    exit_ = pd.Timestamp(trade["ExitDT"])

    view_start = (entry - pd.Timedelta(seconds=config.SCALP_PRE_SEC)).floor(f"{bar}s")
    view_end = max(exit_ + pd.Timedelta(seconds=config.SCALP_POST_SEC),
                   entry + pd.Timedelta(seconds=config.SCALP_MIN_VIEW_SEC)).ceil(f"{bar}s")
    ctx_start = view_start - pd.Timedelta(seconds=config.SCALP_CONTEXT_SEC)

    bars = _load_bars(parquet, ctx_start, view_end, bar)
    if bars.empty or bars["Ticks"].sum() == 0:
        raise ValueError(f"No ticks found around {entry:%d/%m/%Y %H:%M:%S}. "
                         "Does the tick file cover this day?")

    bars["Delta"] = bars["BuyVol"] - bars["SellVol"]
    bars["CumDelta"] = _cum_delta_before(parquet, ctx_start) + bars["Delta"].cumsum()

    for name, sec, ticks in (("S", config.ABS_SHORT_SEC, config.ABS_SHORT_MAX_TICKS),
                             ("L", config.ABS_LONG_SEC, config.ABS_LONG_MAX_TICKS)):
        n = max(1, round(sec / bar))
        bull, bear = _absorption(bars, n, ticks * tick_size)
        bars[f"Bull{name}"] = _cover(bull, n)
        bars[f"Bear{name}"] = _cover(bear, n)

    return bars, view_start, view_end