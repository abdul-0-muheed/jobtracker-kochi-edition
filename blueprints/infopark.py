"""
blueprints/infopark.py — Infopark job listing tab.
Scrapes https://infopark.in/companies-job, renders jobs in a filterable UI,
and lets the user mark jobs as applied (persisted to DB, cross-linked to companies).
"""
from __future__ import annotations

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
    Return cached jobs as JSON, merged with applied status from DB.
    Query params:
      search   — keyword filter (title or company, case-insensitive)
      intern   — if '1', return only internship listings
      applied  — if '1', return only jobs the user applied to
      page     — pagination page (1-indexed, default 1)
      per_page — results per page (default 25)
    """
    from models import InfoparkApplied

    with _lock:
        jobs = list(_cache["jobs"])
        fetched_at = _cache["fetched_at"]
        status = _cache["status"]

    # Build applied URL set from DB
    applied_records = {r.job_url: r for r in InfoparkApplied.query.all()}
    applied_urls = set(applied_records.keys())

    # Merge applied status into jobs
    for job in jobs:
        rec = applied_records.get(job["url"])
        job["applied"] = rec is not None
        job["applied_at"] = rec.applied_at if rec else None
        job["matched_company_id"] = rec.matched_company_id if rec else None

    search = (request.args.get("search") or "").strip().lower()
    intern_only = request.args.get("intern") == "1"
    applied_only = request.args.get("applied") == "1"
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(1, int(request.args.get("per_page", 25)))

    if intern_only:
        jobs = [j for j in jobs if "intern" in j["title"].lower()]

    if applied_only:
        jobs = [j for j in jobs if j["applied"]]

    if search:
        jobs = [
            j for j in jobs
            if search in j["title"].lower() or search in j["company"].lower()
        ]

    total = len(jobs)
    start = (page - 1) * per_page
    end = start + per_page
    page_jobs = jobs[start:end]

    # Pre-match unapplied jobs with our Company DB so the UI can show the company link
    from models import Company
    from rapidfuzz import fuzz, process
    
    all_companies = Company.query.with_entities(Company.id, Company.name).all()
    if all_companies:
        company_dict = {c.name: c.id for c in all_companies}
        company_names = list(company_dict.keys())
        
        for j in page_jobs:
            if not j.get("matched_company_id"):
                match = process.extractOne(j["company"], company_names, scorer=fuzz.token_sort_ratio, score_cutoff=65.0)
                if match:
                    j["matched_company_id"] = company_dict[match[0]]

    return jsonify({
        "jobs":       page_jobs,
        "total":      total,
        "page":       page,
        "per_page":   per_page,
        "pages":      max(1, (total + per_page - 1) // per_page),
        "fetched_at": fetched_at,
        "status":     status,
        "applied_count": len(applied_urls),
    })


@infopark_bp.route("/api/apply", methods=["POST"])
def api_apply():
    """
    Mark an Infopark job as applied.
    Body JSON: { title, company, url, posted_date, last_date }
    - Persists to infopark_applied table
    - Fuzzy-matches company name against companies table
    - If matched, creates an Application record for that company
    Returns: { success, matched_company_id, matched_company_name, application_id }
    """
    from models import InfoparkApplied, Company, Application, db
    from rapidfuzz import process, fuzz

    data = request.get_json(force=True, silent=True) or {}
    job_url   = (data.get("url") or "").strip()
    job_title = (data.get("title") or "").strip()
    company_n = (data.get("company") or "").strip()

    if not job_url or not job_title:
        return jsonify({"error": "url and title are required"}), 400

    now = datetime.now(timezone.utc).isoformat()

    # Check already applied
    existing = InfoparkApplied.query.filter_by(job_url=job_url).first()
    if existing:
        return jsonify({
            "success": True,
            "already_applied": True,
            "matched_company_id": existing.matched_company_id,
        }), 200

    # Fuzzy-match company name against all companies
    all_companies = Company.query.with_entities(Company.id, Company.name).all()
    matched_company_id = None
    matched_company_name = None
    application_id = None

    if all_companies and company_n:
        names = [c.name for c in all_companies]
        result = process.extractOne(company_n, names, scorer=fuzz.token_sort_ratio)
        if result and result[1] >= 65:   # 65% similarity threshold
            matched_name = result[0]
            matched = next(c for c in all_companies if c.name == matched_name)
            matched_company_id = matched.id
            matched_company_name = matched.name

            # Create Application record
            try:
                app_rec = Application(
                    company_id=matched_company_id,
                    role_title=job_title,
                    source="infopark",
                    source_url=job_url,
                    applied_at=now[:10],   # YYYY-MM-DD
                    status="applied",
                    notes=f"Applied via Infopark job board. Company on listing: {company_n}",
                )
                db.session.add(app_rec)
                db.session.flush()
                application_id = app_rec.id

                # Touch company
                company_obj = Company.query.get(matched_company_id)
                if company_obj:
                    company_obj.touch()
            except Exception as exc:
                log.warning(f"Failed to create Application record: {exc}")
                db.session.rollback()
                application_id = None

    # Save infopark_applied record
    rec = InfoparkApplied(
        job_title=job_title,
        company_name=company_n,
        job_url=job_url,
        posted_date=data.get("posted_date") or "",
        last_date=data.get("last_date") or "",
        applied_at=now,
        matched_company_id=matched_company_id,
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({
        "success": True,
        "already_applied": False,
        "matched_company_id": matched_company_id,
        "matched_company_name": matched_company_name,
        "application_id": application_id,
    }), 201


@infopark_bp.route("/api/unapply", methods=["POST"])
def api_unapply():
    """
    Un-mark a job as applied.
    Body JSON: { url }
    Also removes the linked Application record if one was created.
    """
    from models import InfoparkApplied, Application, db

    data = request.get_json(force=True, silent=True) or {}
    job_url = (data.get("url") or "").strip()

    if not job_url:
        return jsonify({"error": "url is required"}), 400

    rec = InfoparkApplied.query.filter_by(job_url=job_url).first()
    if not rec:
        return jsonify({"success": True, "was_applied": False}), 200

    # Remove Application record that was auto-created (source=infopark, source_url matches)
    if rec.matched_company_id:
        app_rec = Application.query.filter_by(
            company_id=rec.matched_company_id,
            source="infopark",
            source_url=job_url,
        ).first()
        if app_rec:
            db.session.delete(app_rec)

    db.session.delete(rec)
    db.session.commit()

    return jsonify({"success": True, "was_applied": True}), 200


@infopark_bp.route("/api/applied")
def api_applied():
    """Return all applied Infopark jobs from DB (for stats / company cross-link)."""
    from models import InfoparkApplied
    records = InfoparkApplied.query.order_by(InfoparkApplied.applied_at.desc()).all()
    return jsonify([r.to_dict() for r in records])


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


@infopark_bp.route("/api/company/<int:cid>")
def api_company(cid: int):
    """
    Return full company details for a matched company.
    Used by the frontend to enrich the agent-context prompt.
    """
    from models import Company
    company = Company.query.get_or_404(cid)
    return jsonify(company.to_dict())


@infopark_bp.route("/api/company_by_name")
def api_company_by_name():
    """
    Fuzzy match a company by name on the fly for unapplied jobs.
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
        
    from models import Company
    from rapidfuzz import fuzz, process
    
    companies = Company.query.all()
    if not companies:
        return jsonify({"error": "No companies"}), 404
        
    company_dict = {c.id: c.name for c in companies}
    match = process.extractOne(
        name,
        company_dict,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=65.0
    )
    
    if match:
        _, score, cid = match
        company = Company.query.get(cid)
        return jsonify(company.to_dict())
        
    return jsonify({"error": "Not found"}), 404
