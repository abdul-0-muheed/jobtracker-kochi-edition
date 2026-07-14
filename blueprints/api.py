"""
blueprints/api.py — JSON API endpoints for charts, reminders, timeline, sync status.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify

from models import Company, FollowUp, Opening, LinkedInEvent, ScrapingJob, db
from blueprints.linkedin import _sync_jobs

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/stats")
def stats():
    """Aggregate stats for dashboard funnel and analytics."""
    funnel = {
        "identified":   Company.query.count(),
        "contacted":    Company.query.filter(Company.contact_status.in_(
                            ["emailed", "replied", "interviewing", "offered"])).count(),
        "replied":      Company.query.filter(Company.contact_status.in_(
                            ["replied", "interviewing", "offered"])).count(),
        "interviewing": Company.query.filter(Company.contact_status == "interviewing").count(),
        "offered":      Company.query.filter(Company.contact_status == "offered").count(),
    }

    # By-industry breakdown
    industry_data: dict[str, dict] = {}
    companies = Company.query.all()
    for c in companies:
        industry = c.industry or "Unknown"
        if industry not in industry_data:
            industry_data[industry] = {"total": 0, "contacted": 0, "replied": 0}
        industry_data[industry]["total"] += 1
        if c.contact_status in ("emailed", "replied", "interviewing", "offered"):
            industry_data[industry]["contacted"] += 1
        if c.contact_status in ("replied", "interviewing", "offered"):
            industry_data[industry]["replied"] += 1

    by_industry = [
        {
            "industry": k,
            "total": v["total"],
            "contacted": v["contacted"],
            "replied": v["replied"],
            "response_rate": round(v["replied"] / v["contacted"] * 100, 1) if v["contacted"] else 0,
        }
        for k, v in sorted(industry_data.items(), key=lambda x: -x[1]["total"])
    ]

    # Recent activity
    recent = (
        Company.query
        .filter(Company.last_activity_at.isnot(None))
        .order_by(Company.last_activity_at.desc())
        .limit(10)
        .all()
    )
    recent_activity = [
        {
            "company_id":   c.id,
            "company_name": c.name,
            "status":       c.contact_status,
            "last_activity": c.last_activity_at,
        }
        for c in recent
    ]

    return jsonify({
        "funnel": funnel,
        "by_industry": by_industry,
        "recent_activity": recent_activity,
    })


@api_bp.route("/reminders")
def reminders():
    """Today's + overdue + upcoming follow-ups."""
    today_str    = date.today().isoformat()
    in_7_days    = (date.today() + timedelta(days=7)).isoformat()

    base = FollowUp.query.filter(FollowUp.status == "pending")

    def _serialize(fu):
        return {
            "id":         fu.id,
            "company_id": fu.company_id,
            "company_name": fu.company.name if fu.company else "—",
            "due_on":     fu.due_on,
            "notes":      fu.notes,
            "status":     fu.status,
        }

    today_list    = [_serialize(f) for f in base.filter(FollowUp.due_on == today_str).all()]
    overdue_list  = [_serialize(f) for f in base.filter(FollowUp.due_on <  today_str).all()]
    upcoming_list = [_serialize(f) for f in base.filter(
        FollowUp.due_on > today_str, FollowUp.due_on <= in_7_days).all()]

    return jsonify({"today": today_list, "overdue": overdue_list, "upcoming": upcoming_list})


@api_bp.route("/companies/<int:cid>/timeline")
def company_timeline(cid: int):
    """JSON timeline for a company — merged events from all sources."""
    company = Company.query.get_or_404(cid)
    events = []

    for ev in company.linkedin_events:
        events.append({
            "type": "linkedin",
            "at": ev.event_at or ev.synced_at,
            "summary": f"LinkedIn: {ev.event_type.replace('_', ' ').title()}",
        })

    for app in company.applications:
        events.append({
            "type": "application",
            "at": app.applied_at or app.created_at,
            "summary": f"Applied: {app.role_title}",
        })

    for fu in company.follow_ups:
        events.append({
            "type": "followup",
            "at": fu.created_at,
            "summary": f"Follow-up ({fu.status}) due {fu.due_on}",
        })

    events.sort(key=lambda x: x.get("at") or "", reverse=True)
    return jsonify(events)


@api_bp.route("/sync-status/<job_id>")
def sync_status(job_id: str):
    """Poll sync job progress."""
    job = _sync_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)
