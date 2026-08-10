from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pandas as pd

REVIEW_COLUMNS = ["trade_id", "process_grade", "setup", "mistake_tag", "notes", "updated_at"]


def load_reviews(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    for col in REVIEW_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[REVIEW_COLUMNS].drop_duplicates("trade_id", keep="last")


def save_review(path: Path, trade_id: str, process_grade: str, setup: str, mistake_tag: str, notes: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    df = load_reviews(path)
    row = {
        "trade_id": trade_id,
        "process_grade": process_grade,
        "setup": setup.strip(),
        "mistake_tag": mistake_tag,
        "notes": notes.strip().replace("\r\n", "\n"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    df = df[df["trade_id"] != trade_id]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def merge_reviews(trades: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    result = trades.merge(reviews, on="trade_id", how="left")
    for col in ["process_grade", "setup", "mistake_tag", "notes"]:
        result[col] = result[col].fillna("")
    result.loc[result["process_grade"].eq(""), "process_grade"] = "Unreviewed"
    return result
