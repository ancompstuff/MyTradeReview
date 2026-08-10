from __future__ import annotations

from pathlib import Path
import pandas as pd

from data_loader import load_trades, finalize_trades, load_market_base, derive_market


TRADE_MASTER_COLUMNS = [
    "Ativo", "Lado", "EntryDT", "ExitDT", "Root", "Side", "BuyPrice", "SellPrice",
    "EntryPrice", "ExitPrice", "PL", "Qty", "trade_id"
]
MARKET_MASTER_COLUMNS = ["Asset", "DateTime", "Open", "High", "Low", "Close", "Volume", "Quantity"]


def _read_master_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def import_trades(source: Path, master_path: Path) -> tuple[int, int]:
    incoming = load_trades(source)
    incoming_core = incoming[[c for c in TRADE_MASTER_COLUMNS if c in incoming.columns]].copy()
    old = _read_master_csv(master_path)
    before = old["trade_id"].nunique() if not old.empty and "trade_id" in old.columns else 0
    combined = pd.concat([old, incoming_core], ignore_index=True) if not old.empty else incoming_core
    combined = combined.drop_duplicates("trade_id", keep="last")
    master_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(master_path, index=False, encoding="utf-8-sig")
    after = combined["trade_id"].nunique()
    return int(after - before), int(after)


def import_market(source: Path, master_path: Path) -> tuple[int, int]:
    incoming = load_market_base(source)
    old = _read_master_csv(master_path)
    if not old.empty:
        old["DateTime"] = pd.to_datetime(old["DateTime"], errors="coerce")
    before = old["DateTime"].nunique() if not old.empty and "DateTime" in old.columns else 0
    combined = pd.concat([old, incoming], ignore_index=True) if not old.empty else incoming
    combined["DateTime"] = pd.to_datetime(combined["DateTime"], errors="coerce")
    combined = combined.dropna(subset=["DateTime"]).sort_values("DateTime").drop_duplicates("DateTime", keep="last")
    combined = combined[[c for c in MARKET_MASTER_COLUMNS if c in combined.columns]]
    master_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(master_path, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")
    after = combined["DateTime"].nunique()
    return int(after - before), int(after)


def load_master_trades(master_path: Path) -> pd.DataFrame:
    df = _read_master_csv(master_path)
    if df.empty:
        return df
    return finalize_trades(df)


def load_master_market(master_path: Path, fast_ma=9, slow_ma=20, long_ma=80) -> pd.DataFrame:
    df = _read_master_csv(master_path)
    if df.empty:
        return df
    return derive_market(df, fast_ma, slow_ma, long_ma)


def bootstrap_if_needed(config_module) -> dict:
    """Build master journal from current data files and preserve earlier reviews on first run."""
    result = {"trades": 0, "WIN": 0, "WDO": 0}
    legacy_reviews = config_module.OUTPUT_DIR / "trade_reviews.csv"
    if not config_module.REVIEWS_FILE.exists() and legacy_reviews.exists():
        config_module.REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config_module.REVIEWS_FILE.write_bytes(legacy_reviews.read_bytes())
    if not config_module.MASTER_TRADES_FILE.exists() and config_module.TRADES_FILE.exists():
        result["trades"], _ = import_trades(config_module.TRADES_FILE, config_module.MASTER_TRADES_FILE)
    if not config_module.MASTER_WIN_FILE.exists() and config_module.WIN_FILE.exists():
        result["WIN"], _ = import_market(config_module.WIN_FILE, config_module.MASTER_WIN_FILE)
    if not config_module.MASTER_WDO_FILE.exists() and config_module.WDO_FILE.exists():
        result["WDO"], _ = import_market(config_module.WDO_FILE, config_module.MASTER_WDO_FILE)
    return result
