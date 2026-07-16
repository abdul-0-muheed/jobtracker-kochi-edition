"""
blueprints/infopark.py — Infopark job listing tab.
Scrapes https://infopark.in/companies-job and renders jobs in a filterable UI.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

log = logging.getLogger(__name__)

infopark_bp = Blueprint("infopark", __name__, url_prefix="/infopark")

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache: dict = {
    "jobs":       [],
    "fetched_at": None,
    "status":     "idle",   # idle | running | done | error
    "error":      None,
}
_lock = threading.Lock()


# ── Views ──────────────────────────────────────────────────────────────────────

@infopark_bp.route("/")
def infopark_jobs():
    """Main Infopark jobs tab."""
    return render_template("infopark.html")


@infopark_bp.route("/api/jobs")
def api_jobs():
    """
    Return cached jobs as JSON.
    Query params:
      search  — keyword filter (title or company, case-insensitive)
      intern  — if '1', return only internship listings
      page    — pagination page (1-indexed, default 1)
      per_page— results per page (default 25)
    """
    with _lock:
        jobs = list(_cache["jobs"])
        fetched_at = _cache["fetched_at"]
        status = _cache["status"]

    search = (request.args.get("search") or "").strip().lower()
    intern_only = request.args.get("intern") == "1"
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(1, int(request.args.get("per_page", 25)))

    if intern_only:
        jobs = [j for j in jobs if "intern" in j["title"].lower()]

    if search:
        jobs = [
            j for j in jobs
            if search in j["title"].lower() or search in j["company"].lower()
        ]

    total = len(jobs)
    start = (page - 1) * per_page
    end = start + per_page
    page_jobs = jobs[start:end]

    return jsonify({
        "jobs":       page_jobs,
        "total":      total,
        "page":       page,
        "per_page":   per_page,
        "pages":      max(1, (total + per_page - 1) // per_page),
        "fetched_at": fetched_at,
        "status":     status,
    })


@infopark_bp.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Trigger a background re-scrape of infopark.in/companies-job."""
    with _lock:
        if _cache["status"] == "running":
            return jsonify({"message": "Scrape already running"}), 409

        _cache["status"] = "running"
        _cache["error"] = None

    def _run():
        from services.infopark_scraper import scrape_infopark_jobs
        try:
            jobs = scrape_infopark_jobs(max_pages=15, delay=0.6)
            with _lock:
                _cache["jobs"] = jobs
                _cache["fetched_at"] = datetime.now(timezone.utc).isoformat()
                _cache["status"] = "done"
            log.info(f"Infopark refresh done: {len(jobs)} jobs")
        except Exception as exc:
            log.error(f"Infopark refresh failed: {exc}")
            with _lock:
                _cache["status"] = "error"
                _cache["error"] = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "Scrape started"}), 202


@infopark_bp.route("/api/status")
def api_status():
    """Return current scrape status."""
    with _lock:
        return jsonify({
            "status":     _cache["status"],
            "total":      len(_cache["jobs"]),
            "fetched_at": _cache["fetched_at"],
            "error":      _cache["error"],
        })
