from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# Reviews output
REVIEWS_FILE = OUTPUT_DIR / "trade_reviews.csv"

# Persist last selected input files from UI picker
SETTINGS_FILE = BASE_DIR / "last_selection.json"

# Picker defaults (change these to wherever you keep your exports)
DEFAULT_TRADES_DIR = DATA_DIR
DEFAULT_MARKET_DIR = DATA_DIR

DEFAULT_TRADES_FILE = DEFAULT_TRADES_DIR / "operations2026.csv"

MARKET_CHOICES = ["WINFUT", "WDOFUT", "BOVESPA"]
DEFAULT_MARKET_CHOICE = "WINFUT"

DEFAULT_MARKET_FILES = {
    "WINFUT": DEFAULT_MARKET_DIR / "WINFUT_F_0_1min.csv",
    "WDOFUT": DEFAULT_MARKET_DIR / "WDOFUT_F_0_1min.csv",
    "BOVESPA": DEFAULT_MARKET_DIR / "BOVESPA_1min.csv",
}

# Chart settings
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

# --- Tick / scalp analysis ---
TICK_CACHE_DIR = BASE_DIR / "cache" / "ticks"
TICK_ENCODING = "latin-1"          # ISO 8859-1

TICK_SIZE = {"WIN": 5.0, "WDO": 0.5, "BOVESPA": 0.01}

SCALP_AUTO_MAX_SEC = 500           # trades up to 5 min open the scalp chart by default
SCALP_PRE_SEC = 180                # seconds shown before entry
SCALP_POST_SEC = 60                # seconds shown after exit
SCALP_MIN_VIEW_SEC = 45            # minimum seconds shown after entry
SCALP_CONTEXT_SEC = 900            # extra history used only to calibrate thresholds
SCALP_BAR_SEC = 1                  # bar size in seconds

# Absorption heuristics (tune these)
ABS_SHORT_SEC = 5
ABS_SHORT_MAX_TICKS = 1            # price may move at most this many ticks
ABS_LONG_SEC = 60
ABS_LONG_MAX_TICKS = 4
ABS_VOL_QUANTILE = 0.90            # "heavy" = top 10% of rolling volume
ABS_DOMINANCE = 1.3                # heavy side must exceed the other side by 30%