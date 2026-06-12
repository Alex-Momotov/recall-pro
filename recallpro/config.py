from pathlib import Path

RECALLPRO_DIR = Path.home() / ".recallpro"
DB_PATH = RECALLPRO_DIR / "recallpro.db"
CREDENTIALS_PATH = RECALLPRO_DIR / "credentials.json"
TOKEN_PATH = RECALLPRO_DIR / "token.json"
LOG_PATH = RECALLPRO_DIR / "daemon.log"

PLIST_LABEL = "com.recallpro.agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
DAEMON_INTERVAL_SECONDS = 900

GTASKS_LIST_TITLE = "Revisions"

# Pre-rename locations (app was "recall", then a user-specific agent label)
LEGACY_DATA_DIR = Path.home() / ".recall"
LEGACY_PLIST_PATHS = [
    Path.home() / "Library" / "LaunchAgents" / "com.alex.recall.plist",
    Path.home() / "Library" / "LaunchAgents" / "com.alex.recallpro.plist",
]


def migrate_legacy_data() -> None:
    """One-time, idempotent: move ~/.recall → ~/.recallpro and rename the
    db file inside. Safe to call on every startup."""
    if LEGACY_DATA_DIR.exists() and not RECALLPRO_DIR.exists():
        LEGACY_DATA_DIR.rename(RECALLPRO_DIR)
    legacy_db = RECALLPRO_DIR / "recall.db"
    if legacy_db.exists() and not DB_PATH.exists():
        legacy_db.rename(DB_PATH)
