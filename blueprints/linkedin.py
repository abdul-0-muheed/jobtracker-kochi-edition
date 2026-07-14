"""
blueprints/linkedin.py — LinkedIn session management and sync.

Auth flow:
  1. User goes to /linkedin/auth → enters passphrase
  2. POST to /linkedin/auth/start → saves passphrase in server session,
     spawns Playwright chromium subprocess via a Python script
  3. /linkedin/status shows connection state
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session as flask_session, url_for,
)

from config import SESSION_DIR, load_settings, save_settings
from models import Company, Contact, LinkedInEvent, ScrapingJob, db

log = logging.getLogger(__name__)
linkedin_bp = Blueprint("linkedin", __name__, url_prefix="/linkedin")

SESSION_FILE = SESSION_DIR / "linkedin.enc"

# In-memory sync job state (keyed by job_id string)
_sync_jobs: dict[str, dict] = {}


# ── Status page ───────────────────────────────────────────────────────────────
@linkedin_bp.route("/")
def linkedin_status():
    settings = load_settings()
    jobs = (
        ScrapingJob.query
        .filter(ScrapingJob.scraper_type == "linkedin_sync")
        .order_by(ScrapingJob.started_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "linkedin.html",
        settings=settings,
        session_exists=SESSION_FILE.exists(),
        sync_history=jobs,
    )


# ── Auth ──────────────────────────────────────────────────────────────────────
@linkedin_bp.route("/auth", methods=["GET"])
def auth():
    return render_template("linkedin_auth.html")


@linkedin_bp.route("/auth/start", methods=["POST"])
def auth_start():
    """
    Store the passphrase in the Flask session, then show the user
    a command to run in their own terminal to open the browser.
    """
    passphrase = request.form.get("passphrase", "").strip()
    confirm    = request.form.get("confirm_passphrase", "").strip()

    if not passphrase:
        flash("Please enter a passphrase.", "danger")
        return redirect(url_for("linkedin.auth"))

    if passphrase != confirm:
        flash("Passphrases do not match. Please try again.", "danger")
        return redirect(url_for("linkedin.auth"))

    # Store passphrase temporarily in server-side session
    flask_session["li_passphrase"] = passphrase
    return redirect(url_for("linkedin.auth_waiting"))


@linkedin_bp.route("/auth/waiting")
def auth_waiting():
    """Show the user the command to run to open the browser."""
    import sys
    helper = Path(__file__).parent.parent / "linkedin_login_helper.py"
    passphrase = flask_session.get("li_passphrase", "YOUR_PASSPHRASE")
    cmd = f'python "{helper}" "{passphrase}"'
    return render_template("linkedin_waiting.html", cmd=cmd,
                           session_exists=SESSION_FILE.exists())


@linkedin_bp.route("/auth/check")
def auth_check():
    """Poll endpoint — returns whether the session file now exists."""
    exists = SESSION_FILE.exists()
    if exists:
        # Clean up passphrase from session
        flask_session.pop("li_passphrase", None)
        s = load_settings()
        s["linkedin"]["connected"] = True
        save_settings(s)
    return jsonify({"connected": exists})


# ── Sync ──────────────────────────────────────────────────────────────────────
@linkedin_bp.route("/sync", methods=["POST"])
def trigger_sync():
    """Trigger a background LinkedIn sync. Returns job_id for polling."""
    import uuid
    job_id = str(uuid.uuid4())[:8]

    data = request.form or (request.get_json(force=True, silent=True) or {})
    passphrase = data.get("passphrase", "")

    if not passphrase:
        return jsonify({"error": "Passphrase required"}), 400

    _sync_jobs[job_id] = {
        "status": "running", "items_processed": 0, "items_new": 0, "error": None
    }

    sj = ScrapingJob(scraper_type="linkedin_sync", status="running")
    db.session.add(sj)
    db.session.commit()
    db_job_id = sj.id

    from flask import current_app
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run_sync_with_app,
        args=(app, job_id, db_job_id, passphrase),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


def _run_sync_with_app(app, job_id: str, db_job_id: int, passphrase: str):
    with app.app_context():
        _do_sync(job_id, db_job_id, passphrase)


def _do_sync(job_id: str, db_job_id: int, passphrase: str):
    from services.linkedin_client import (
        open_browser_with_session, scrape_sent_invitations, scrape_messages,
    )
    from services.matching import match_company

    state = _sync_jobs[job_id]
    sj    = ScrapingJob.query.get(db_job_id)

    try:
        if not SESSION_FILE.exists():
            raise RuntimeError(
                "No LinkedIn session found. Please connect LinkedIn first via the Connect button."
            )

        from playwright.sync_api import sync_playwright
        companies = Company.query.all()
        items_new = 0

        with sync_playwright() as pw:
            browser, context, page = open_browser_with_session(pw, passphrase, SESSION_FILE)

            # ── Invitations ───────────────────────────────────────────────────
            invitations = scrape_sent_invitations(page, max_scroll=5)
            state["items_processed"] = len(invitations)

            for inv in invitations:
                match_result = match_company(inv.get("company", ""), companies)
                if not match_result:
                    continue
                matched_company, _ = match_result

                contact = None
                if inv.get("profile_url"):
                    contact = Contact.query.filter_by(
                        linkedin_profile_url=inv["profile_url"]
                    ).first()
                if not contact and inv.get("name"):
                    contact = Contact(
                        company_id=matched_company.id,
                        name=inv["name"],
                        linkedin_profile_url=inv.get("profile_url"),
                        linkedin_headline=inv.get("headline"),
                        contact_type="employee",
                    )
                    db.session.add(contact)
                    db.session.flush()

                try:
                    ev = LinkedInEvent(
                        company_id=matched_company.id,
                        contact_id=contact.id if contact else None,
                        event_type="connection_sent",
                        event_at=datetime.now(timezone.utc).isoformat(),
                        raw_payload=json.dumps(inv),
                    )
                    db.session.add(ev)
                    db.session.flush()
                    matched_company.touch()
                    items_new += 1
                except Exception:
                    db.session.rollback()

            db.session.commit()
            state["items_new"] = items_new

            # ── Messages ──────────────────────────────────────────────────────
            try:
                messages = scrape_messages(page, max_threads=30)
                for msg in messages:
                    match_result = match_company(msg.get("recipient_company", ""), companies)
                    if not match_result:
                        continue
                    matched_company, _ = match_result
                    try:
                        ev = LinkedInEvent(
                            company_id=matched_company.id,
                            event_type="message_sent",
                            event_at=datetime.now(timezone.utc).isoformat(),
                            raw_payload=json.dumps(msg),
                        )
                        db.session.add(ev)
                        db.session.flush()
                        matched_company.touch()
                        items_new += 1
                    except Exception:
                        db.session.rollback()
                db.session.commit()
            except Exception as e:
                log.warning(f"Message scrape failed: {e}")

            browser.close()

        sj.status = "success"
        sj.finished_at = datetime.now(timezone.utc).isoformat()
        sj.items_processed = state["items_processed"]
        sj.items_new = items_new
        db.session.commit()

        state["status"] = "success"
        state["items_new"] = items_new

        s = load_settings()
        s["linkedin"]["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        save_settings(s)

    except RuntimeError as e:
        log.error(f"Sync aborted: {e}")
        state["status"] = "aborted"
        state["error"] = str(e)
        if sj:
            sj.status = "aborted"
            sj.error_message = str(e)
            sj.finished_at = datetime.now(timezone.utc).isoformat()
            db.session.commit()
    except Exception as e:
        log.exception(f"Sync failed: {e}")
        state["status"] = "failed"
        state["error"] = str(e)
        if sj:
            sj.status = "failed"
            sj.error_message = str(e)
            sj.finished_at = datetime.now(timezone.utc).isoformat()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()


# ── Revoke ────────────────────────────────────────────────────────────────────
@linkedin_bp.route("/revoke", methods=["POST"])
def revoke_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    s = load_settings()
    s["linkedin"]["connected"] = False
    s["linkedin"]["user_name"] = None
    save_settings(s)
    flash("LinkedIn session revoked.", "info")
    return redirect(url_for("linkedin.linkedin_status"))


# ── Reset Passphrase ──────────────────────────────────────────────────────────
@linkedin_bp.route("/reset-passphrase", methods=["POST"])
def reset_passphrase():
    """Delete the encrypted session file and redirect to set a new passphrase."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        log.info("LinkedIn session file deleted for passphrase reset.")
    s = load_settings()
    s["linkedin"]["connected"] = False
    s["linkedin"]["user_name"] = None
    save_settings(s)
    flash(
        "Session cleared. Please log in to LinkedIn again and set a new passphrase.",
        "info"
    )
    return redirect(url_for("linkedin.auth"))
