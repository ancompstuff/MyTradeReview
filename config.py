from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
JOURNAL_DIR = BASE_DIR / "journal"
CHARTS_DIR = OUTPUT_DIR / "charts"

# Current/source exports. These are used to bootstrap the journal the first time.
TRADES_FILE = DATA_DIR / "operations2026.csv"
WIN_FILE = DATA_DIR / "WINFUT_F_0_1min.csv"
WDO_FILE = DATA_DIR / "WDOFUT_F_0_1min.csv"

# Persistent master journal. New imports are merged into these files; duplicates are ignored.
MASTER_TRADES_FILE = JOURNAL_DIR / "trades_master.csv"
MASTER_WIN_FILE = JOURNAL_DIR / "WIN_1min_master.csv"
MASTER_WDO_FILE = JOURNAL_DIR / "WDO_1min_master.csv"
REVIEWS_FILE = JOURNAL_DIR / "trade_reviews.csv"
ANNOTATIONS_FILE = JOURNAL_DIR / "chart_annotations.json"

PRE_ENTRY_MINUTES = 50
POST_EXIT_BARS = 10
FIGSIZE = (12, 9)
FIG_DPI = 100

MA_FAST = 9
MA_SLOW = 20
MA_LONG = 80

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

# OneNote integration (Microsoft Graph). The client ID is stored locally in this JSON,
# not in Git. It is an application identifier, not a client secret.
ONENOTE_SETTINGS_FILE = JOURNAL_DIR / "onenote_settings.json"
ONENOTE_TOKEN_CACHE_FILE = JOURNAL_DIR / "onenote_token_cache.json"
ONENOTE_SYNC_MAP_FILE = JOURNAL_DIR / "onenote_sync.json"
