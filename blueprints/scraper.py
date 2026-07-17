"""
blueprints/scraper.py — Career page job scanning.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from models import Company, Opening, ScrapingJob, db
from services.career_scraper import scrape_career_page

log = logging.getLogger(__name__)
scraper_bp = Blueprint("scraper", __name__, url_prefix="/scrape")


@scraper_bp.route("/jobs/<int:company_id>", methods=["POST"])
def scan_company_jobs(company_id: int):
    """Trigger immediate career page + LinkedIn jobs scan for one company."""
    company = Company.query.get_or_404(company_id)

    sj = ScrapingJob(
        scraper_type="career_page_scan",
        target_company_id=company_id,
        status="running",
    )
    db.session.add(sj)
    db.session.commit()

    openings_found = 0
    new_count = 0

    try:
        if company.career_page_url:
            jobs = scrape_career_page(company.career_page_url, delay=(1, 3))
            now = datetime.now(timezone.utc).isoformat()

            # Mark existing openings as potentially closed
            existing_urls = {o.url for o in company.openings if o.status == "open"}
            seen_urls = set()

            for job in jobs:
                openings_found += 1
                url   = job.get("url") or ""
                title = (job.get("title") or "").strip()
                if not title:
                    continue

                seen_urls.add(url)

                # Try to update existing by title+url combo
                existing = Opening.query.filter_by(
                    company_id=company_id, title=title
                ).first()

                if existing:
                    existing.last_seen_at = now
                    existing.status = "open"
                    if url and not existing.url:
                        existing.url = url
                else:
                    try:
                        o = Opening(
                            company_id=company_id,
                            title=title,
                            location=job.get("location") or "",
                            url=url,
                            source=job.get("source", "career_page"),
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                        db.session.add(o)
                        db.session.flush()   # Detect constraint errors early
                        new_count += 1
                    except Exception as insert_err:
                        db.session.rollback()
                        log.debug(f"Skipping duplicate opening '{title}': {insert_err}")

            # Mark disappeared openings as closed
            for o in company.openings:
                if o.status == "open" and o.url and o.url not in seen_urls:
                    o.status = "closed"

            company.touch()
            db.session.commit()

        # Update scraping_job
        sj.status = "success"
        sj.finished_at = datetime.now(timezone.utc).isoformat()
        sj.items_processed = openings_found
        sj.items_new = new_count
        db.session.commit()

    except Exception as e:
        log.error(f"Scan failed for company {company_id}: {e}")
        sj.status = "failed"
        sj.error_message = str(e)
        sj.finished_at = datetime.now(timezone.utc).isoformat()
        db.session.commit()

    return jsonify({
        "openings_found": openings_found,
        "new_count": new_count,
        "status": sj.status,
        "jobs": [],   # detail omitted for performance; view on company detail page
    })


# ── Bulk Scan (all companies) ─────────────────────────────────────────────────
import threading
import uuid

_bulk_jobs: dict[str, dict] = {}
_latest_bulk_job_id = None


@scraper_bp.route("/jobs/all", methods=["POST"])
def scan_all_companies():
    """Trigger background career page scan for ALL companies that have career pages."""
    from flask import current_app
    app = current_app._get_current_object()
    
    global _latest_bulk_job_id
    job_id = str(uuid.uuid4())[:8]
    _latest_bulk_job_id = job_id
    _bulk_jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "total": 0,
        "done": 0,
        "openings_found": 0,
        "new_count": 0,
        "errors": [],
    }

    def _run():
        with app.app_context():
            companies = Company.query.filter(
                Company.career_page_url.isnot(None),
                Company.career_page_url != "",
            ).order_by(Company.match_score.desc()).all()

            state = _bulk_jobs[job_id]
            state["total"] = len(companies)

            for company in companies:
                try:
                    jobs = scrape_career_page(company.career_page_url, delay=(2, 5))
                    now = datetime.now(timezone.utc).isoformat()
                    seen_urls = set()

                    for job in jobs:
                        title = (job.get("title") or "").strip()
                        url = job.get("url") or ""
                        posted_date = job.get("posted_date")
                        deadline = job.get("deadline")
                        if not title:
                            continue
                        seen_urls.add(url)
                        state["openings_found"] += 1

                        existing = Opening.query.filter_by(
                            company_id=company.id, title=title
                        ).first()
                        if existing:
                            existing.last_seen_at = now
                            existing.status = "open"
                            if posted_date:
                                existing.first_seen_at = posted_date
                            if deadline:
                                existing.deadline = deadline
                        else:
                            try:
                                o = Opening(
                                    company_id=company.id,
                                    title=title,
                                    location=job.get("location") or "",
                                    url=url,
                                    source=job.get("source", "career_page"),
                                    first_seen_at=posted_date if posted_date else now,
                                    last_seen_at=now,
                                    deadline=deadline
                                )
                                db.session.add(o)
                                db.session.flush()
                                state["new_count"] += 1
                            except Exception:
                                db.session.rollback()

                    for o in company.openings:
                        if o.status == "open" and o.url and o.url not in seen_urls:
                            o.status = "closed"

                    company.touch()
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    state["errors"].append(f"{company.name}: {e}")
                    log.warning(f"Bulk scan error for {company.name}: {e}")

                state["done"] += 1

            state["status"] = "done"
            log.info(f"Bulk scan complete: {state['new_count']} new openings across {state['total']} companies")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id, "message": "Bulk scan started"}), 202


@scraper_bp.route("/status/latest")
def scan_status_latest():
    """Poll progress of the most recently started bulk scan."""
    if not _latest_bulk_job_id or _latest_bulk_job_id not in _bulk_jobs:
        return jsonify({"status": "idle"}), 200
    return jsonify(_bulk_jobs[_latest_bulk_job_id])


@scraper_bp.route("/status/<job_id>")
def scan_status(job_id: str):
    """Poll bulk scan progress."""
    state = _bulk_jobs.get(job_id)
    if not state:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(state)


@scraper_bp.route("/openings/summary")
def openings_summary():
    """Return count of open openings per company (for dashboard)."""
    from sqlalchemy import func
    rows = (
        db.session.query(
            Opening.company_id,
            func.count(Opening.id).label("count"),
        )
        .filter(Opening.status == "open")
        .group_by(Opening.company_id)
        .all()
    )
    return jsonify({str(r.company_id): r.count for r in rows})

