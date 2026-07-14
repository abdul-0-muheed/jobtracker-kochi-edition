"""
config.py — Application configuration and path management.
All paths are rooted under ~/.jobtracker so the app is fully portable.
"""
import json
import os
from pathlib import Path

# ── Directory layout ──────────────────────────────────────────────────────────
DATA_DIR    = Path.home() / ".jobtracker"
DB_PATH     = DATA_DIR / "data.db"
SESSION_DIR = DATA_DIR / ".sessions"
BACKUP_DIR  = DATA_DIR / "backups"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOCK_FILE   = DATA_DIR / ".lock"

# Ensure all directories exist on import
for _dir in (DATA_DIR, SESSION_DIR, BACKUP_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# ── Default settings ──────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "reminders": {
        "follow_up_cadence_days": 5,
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "08:00",
        "daily_digest_enabled": True,
        "daily_digest_time": "08:00",
    },
    "scraping": {
        "career_page_delay_min": 5,
        "career_page_delay_max": 10,
        "linkedin_delay_min": 8,
        "linkedin_delay_max": 15,
        "max_linkedin_pages_per_sync": 30,
        "career_page_schedule_hours": 24,
        "linkedin_sync_schedule_hours": 6,
    },
    "linkedin": {
        "session_file": str(SESSION_DIR / "linkedin.enc"),
        "connected": False,
        "user_name": None,
        "last_sync_at": None,
    },
}


def load_settings() -> dict:
    """Load settings from disk, merging with defaults for missing keys."""
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # Deep-merge: defaults fill in any missing keys
        merged = DEFAULT_SETTINGS.copy()
        for section, values in saved.items():
            if section in merged and isinstance(values, dict):
                merged[section].update(values)
            else:
                merged[section] = values
        return merged
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    """Persist settings dict to disk as JSON."""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# ── Flask config ──────────────────────────────────────────────────────────────
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-production")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = str(DATA_DIR / "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

    # Ensure upload folder exists
    Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
