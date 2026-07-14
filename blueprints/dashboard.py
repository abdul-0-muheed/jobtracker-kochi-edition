"""
blueprints/dashboard.py — Home dashboard and settings.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone

from flask import (
    Blueprint, Response, flash, redirect, render_template,
    request, url_for,
)

from config import load_settings, save_settings
from models import Company, FollowUp, Opening, db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    # Funnel counts
    statuses = ["not_contacted", "emailed", "replied", "interviewing", "offered", "rejected", "cold"]
    funnel = {
        "identified":  Company.query.count(),
        "contacted":   Company.query.filter(Company.contact_status.in_(
                           ["emailed", "replied", "interviewing", "offered"])).count(),
        "replied":     Company.query.filter(Company.contact_status.in_(
                           ["replied", "interviewing", "offered"])).count(),
        "interviewing":Company.query.filter(Company.contact_status == "interviewing").count(),
        "offered":     Company.query.filter(Company.contact_status == "offered").count(),
    }

    today_str = date.today().isoformat()

    # Today's follow-ups
    today_followups = (
        FollowUp.query
        .filter(FollowUp.status == "pending", FollowUp.due_on == today_str)
        .order_by(FollowUp.due_on)
        .limit(20)
        .all()
    )

    # Overdue
    overdue = (
        FollowUp.query
        .filter(FollowUp.status == "pending", FollowUp.due_on < today_str)
        .count()
    )

    # New openings (last 24h)
    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    new_openings = (
        Opening.query
        .filter(Opening.status == "open", Opening.first_seen_at >= yesterday)
        .order_by(Opening.first_seen_at.desc())
        .limit(10)
        .all()
    )

    # Recent activity (all companies sorted by last_activity_at)
    recent_companies = (
        Company.query
        .filter(Company.last_activity_at.isnot(None))
        .order_by(Company.last_activity_at.desc())
        .limit(20)
        .all()
    )

    settings = load_settings()

    return render_template(
        "dashboard.html",
        funnel=funnel,
        today_followups=today_followups,
        overdue_count=overdue,
        new_openings=new_openings,
        recent_companies=recent_companies,
        settings=settings,
    )


@dashboard_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        tab = request.form.get("tab", "reminders")
        current = load_settings()

        if tab == "reminders":
            current["reminders"]["follow_up_cadence_days"] = int(
                request.form.get("follow_up_cadence_days", 5))
            current["reminders"]["quiet_hours_start"] = request.form.get("quiet_hours_start", "21:00")
            current["reminders"]["quiet_hours_end"]   = request.form.get("quiet_hours_end", "08:00")
            current["reminders"]["daily_digest_enabled"] = bool(request.form.get("daily_digest_enabled"))
            current["reminders"]["daily_digest_time"]    = request.form.get("daily_digest_time", "08:00")

        elif tab == "scraping":
            current["scraping"]["career_page_delay_min"] = int(request.form.get("career_page_delay_min", 5))
            current["scraping"]["career_page_delay_max"] = int(request.form.get("career_page_delay_max", 10))
            current["scraping"]["linkedin_delay_min"]    = int(request.form.get("linkedin_delay_min", 8))
            current["scraping"]["linkedin_delay_max"]    = int(request.form.get("linkedin_delay_max", 15))
            current["scraping"]["max_linkedin_pages_per_sync"] = int(
                request.form.get("max_linkedin_pages_per_sync", 30))

        save_settings(current)
        flash("Settings saved.", "success")
        return redirect(url_for("dashboard.settings") + f"#tab-{tab}")

    current = load_settings()
    return render_template("settings.html", settings=current)
