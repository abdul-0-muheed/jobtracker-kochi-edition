"""
app.py — Flask application factory.
Creates the app, registers blueprints, initializes DB, and sets up APScheduler.
"""
import shutil
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config, DATA_DIR, DB_PATH, BACKUP_DIR, load_settings
from models import db


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Database ───────────────────────────────────────────────────────────────
    db.init_app(app)

    with app.app_context():
        # Enable FK enforcement for every connection
        from sqlalchemy import event, text
        from sqlalchemy.engine import Engine
        import sqlite3

        @event.listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        db.create_all()
        log.info(f"Database ready at {DB_PATH}")

    # ── Blueprints ─────────────────────────────────────────────────────────────
    from blueprints.dashboard  import dashboard_bp
    from blueprints.companies  import companies_bp
    from blueprints.linkedin   import linkedin_bp
    from blueprints.scraper    import scraper_bp
    from blueprints.api        import api_bp
    from blueprints.infopark   import infopark_bp
    from blueprints.jobs       import jobs_bp
    from blueprints.linkedin_scraper import linkedin_scraper_bp
    from blueprints.aggregator import aggregator_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(companies_bp)
    app.register_blueprint(linkedin_bp)
    app.register_blueprint(scraper_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(infopark_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(linkedin_scraper_bp)
    app.register_blueprint(aggregator_bp)

    # ── Jinja2 helpers ─────────────────────────────────────────────────────────
    @app.template_filter("datetimeformat")
    def _datetimeformat(value: str, fmt: str = "%b %d, %Y") -> str:
        if not value:
            return "—"
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime(fmt)
        except Exception:
            return value

    @app.template_filter("reltime")
    def _reltime(value: str) -> str:
        """Return a human-readable relative time like '3 days ago'."""
        if not value:
            return "never"
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            seconds = int(delta.total_seconds())
            if seconds < 60:
                return "just now"
            if seconds < 3600:
                return f"{seconds // 60}m ago"
            if seconds < 86400:
                return f"{seconds // 3600}h ago"
            days = seconds // 86400
            if days == 1:
                return "yesterday"
            if days < 30:
                return f"{days} days ago"
            if days < 365:
                return f"{days // 30}mo ago"
            return f"{days // 365}y ago"
        except Exception:
            return value

    @app.context_processor
    def _inject_globals():
        from services.reminders import count_due_today
        try:
            due_count = count_due_today()
        except Exception:
            due_count = 0
        return dict(due_today_count=due_count)

    # ── APScheduler ────────────────────────────────────────────────────────────
    scheduler = BackgroundScheduler(daemon=True)

    def _daily_backup():
        """Copy SQLite DB to backup dir, keep last 30."""
        stamp = datetime.now().strftime("%Y-%m-%d")
        dest = BACKUP_DIR / f"data-{stamp}.db"
        try:
            shutil.copy2(DB_PATH, dest)
            # Prune old backups
            backups = sorted(BACKUP_DIR.glob("data-*.db"))
            for old in backups[:-30]:
                old.unlink()
            log.info(f"Backup created: {dest}")
        except Exception as e:
            log.error(f"Backup failed: {e}")

    scheduler.add_job(_daily_backup, "cron", hour=3, minute=0, id="daily_backup")
    scheduler.start()
    log.info("APScheduler started")

    return app
