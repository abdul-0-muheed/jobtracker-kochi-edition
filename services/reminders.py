"""
services/reminders.py — Business-day follow-up date computation and due-reminder queries.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def add_business_days(start: date, n: int) -> date:
    """
    Return the date n business days after start, skipping Saturday and Sunday.
    Example: add_business_days(Friday, 5) → next Friday
    """
    current = start
    added = 0
    while added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:   # Mon=0 … Fri=4
            added += 1
    return current


def due_on_for_email(sent_at: date, cadence_days: int = 5) -> date:
    """Compute the follow-up due date for an HR email."""
    return add_business_days(sent_at, cadence_days)


def count_due_today() -> int:
    """Return count of follow-ups due today or overdue (status=pending)."""
    from models import FollowUp, db
    today_str = date.today().isoformat()
    try:
        return db.session.query(FollowUp).filter(
            FollowUp.status == "pending",
            FollowUp.due_on <= today_str,
        ).count()
    except Exception:
        return 0


def get_due_reminders() -> dict:
    """
    Return a dict with keys:
        today    — follow-ups due today
        overdue  — follow-ups past due (excluding today)
        upcoming — follow-ups due in the next 7 days (exclusive of today)
    """
    from models import FollowUp, Company, db

    today_str    = date.today().isoformat()
    in_7_days    = (date.today() + timedelta(days=7)).isoformat()

    base = db.session.query(FollowUp).filter(FollowUp.status == "pending")

    today_list    = base.filter(FollowUp.due_on == today_str).all()
    overdue_list  = base.filter(FollowUp.due_on <  today_str).all()
    upcoming_list = base.filter(
        FollowUp.due_on > today_str,
        FollowUp.due_on <= in_7_days,
    ).all()

    return {
        "today":    [f.to_dict() for f in today_list],
        "overdue":  [f.to_dict() for f in overdue_list],
        "upcoming": [f.to_dict() for f in upcoming_list],
    }
