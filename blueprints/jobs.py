"""
blueprints/jobs.py — Shows scraped jobs from Deep Scraper in a dedicated Jobs page.
Uses the ScrapedJob table (not linked to Company CRM).
"""
from __future__ import annotations

import logging
from flask import Blueprint, render_template, request, jsonify

from models import ScrapedJob, db

log = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__, url_prefix="/jobs")


@jobs_bp.route("/")
def index():
    search = request.args.get("search", "").strip()
    source_filter = request.args.get("source", "").strip()
    sort = request.args.get("sort", "recent")
    intern_only = request.args.get("intern", "0") == "1"
    type_filter = request.args.get("type", "").strip()   # startup | mnc | it
    status_filter = request.args.get("status", "").strip() # saved | applied | dismissed | all | new
    page = request.args.get("page", 1, type=int)
    per_page = 30
    
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    query = ScrapedJob.query

    if search:
        query = query.filter(
            db.or_(
                ScrapedJob.title.ilike(f"%{search}%"),
                ScrapedJob.company.ilike(f"%{search}%")
            )
        )

    if intern_only:
        query = query.filter(ScrapedJob.title.ilike("%intern%"))

    if source_filter:
        query = query.filter(ScrapedJob.source == source_filter)

    if type_filter == "startup":
        query = query.filter(ScrapedJob.company_type.ilike("%startup%"))
    elif type_filter == "mnc":
        query = query.filter(
            db.or_(
                ScrapedJob.company_type.ilike("%mnc%"),
                ScrapedJob.company_type.ilike("%corporate%")
            )
        )
    elif type_filter == "it":
        query = query.filter(ScrapedJob.company_type.ilike("%it%"))

    if sort == "score":
        query = query.order_by(ScrapedJob.ats_score.desc())
    else:
        query = query.order_by(ScrapedJob.scraped_at.desc())

    if status_filter == "all":
        pass # show all
    elif status_filter in ("saved", "applied", "dismissed", "new"):
        query = query.filter(ScrapedJob.status == status_filter)
    else:
        # Default: hide dismissed jobs
        query = query.filter(ScrapedJob.status != "dismissed")

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get unique sources for filter dropdown
    sources = [r[0] for r in db.session.query(ScrapedJob.source).distinct().all() if r[0]]
    total_jobs = ScrapedJob.query.count()
    intern_count = ScrapedJob.query.filter(ScrapedJob.title.ilike("%intern%")).count()
    startup_count = ScrapedJob.query.filter(ScrapedJob.company_type.ilike("%startup%")).count()

    return render_template(
        "jobs.html",
        jobs=pagination.items,
        pagination=pagination,
        search=search,
        source_filter=source_filter,
        sources=sources,
        sort=sort,
        intern_only=intern_only,
        type_filter=type_filter,
        status_filter=status_filter,
        total_jobs=total_jobs,
        intern_count=intern_count,
        startup_count=startup_count,
        today_str=today_str,
    )


@jobs_bp.route("/<int:job_id>/status", methods=["POST"])
def update_status(job_id):
    """Update job status (saved / applied / dismissed)."""
    job = ScrapedJob.query.get_or_404(job_id)
    new_status = request.json.get("status")
    if new_status in ("new", "saved", "applied", "dismissed"):
        job.status = new_status
        db.session.commit()
        return jsonify({"ok": True})
    return jsonify({"error": "Invalid status"}), 400
