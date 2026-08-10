from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

TRADES_FILE = DATA_DIR / "operations2026.csv"
WIN_FILE = DATA_DIR / "WINFUT_F_0_1min.csv"
WDO_FILE = DATA_DIR / "WDOFUT_F_0_1min.csv"
REVIEWS_FILE = OUTPUT_DIR / "trade_reviews.csv"

PRE_ENTRY_MINUTES = 50
POST_EXIT_BARS = 10
FIGSIZE = (12, 9)
FIG_DPI = 100

MA_FAST = 9
MA_SLOW = 20

PROCESS_GRADES = [
    "Unreviewed",
    "A - Good process",
    "B - Acceptable",
    "C - Questionable",
    "D - Poor process",
]

MISTAKE_TAGS = [
    "",
    "Good trade / no clear mistake",
    "Entry too early",
    "Entry too late / chased",
    "Against short-term trend",
    "Poor location",
    "Stop too tight",
    "Stop too wide",
    "Took profit too early",
    "Held loser too long",
    "Rapid re-entry / overtrading",
    "Revenge / impulse trade",
    "Other",
]
