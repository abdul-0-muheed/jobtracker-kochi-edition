"""
tests/test_reminders.py — Unit tests for services/reminders.py
"""
import pytest
from datetime import date
from services.reminders import add_business_days, due_on_for_email


# ── add_business_days ─────────────────────────────────────────────────────────

def test_add_business_days_normal():
    # Monday + 5 business days = Monday (skips Sat/Sun)
    start = date(2026, 7, 6)   # Monday
    result = add_business_days(start, 5)
    assert result == date(2026, 7, 13)   # next Monday


def test_add_business_days_zero():
    start = date(2026, 7, 6)
    assert add_business_days(start, 0) == start


def test_add_business_days_skips_weekend():
    # Friday + 1 business day = Monday
    friday = date(2026, 7, 3)    # Friday
    result = add_business_days(friday, 1)
    assert result == date(2026, 7, 6)    # Monday


def test_add_business_days_from_weekend():
    # If start is Saturday, +1 business day = Monday
    saturday = date(2026, 7, 4)
    result = add_business_days(saturday, 1)
    assert result == date(2026, 7, 6)    # Monday


def test_add_business_days_5_from_friday():
    friday = date(2026, 7, 3)
    result = add_business_days(friday, 5)
    assert result == date(2026, 7, 10)   # Friday next week


def test_add_business_days_10():
    # 10 business days from Monday = 2 weeks later (same day)
    monday = date(2026, 7, 6)
    result = add_business_days(monday, 10)
    assert result == date(2026, 7, 20)


def test_add_business_days_across_month():
    # From July 30 (Thursday) + 5 business days
    start = date(2026, 7, 30)
    result = add_business_days(start, 5)
    assert result == date(2026, 8, 6)   # Thursday Aug 6


# ── due_on_for_email ──────────────────────────────────────────────────────────

def test_due_on_for_email_default_cadence():
    sent = date(2026, 7, 6)   # Monday
    result = due_on_for_email(sent)
    # Default cadence = 5 business days → Monday + 5bd = Monday
    assert result == date(2026, 7, 13)


def test_due_on_for_email_custom_cadence():
    sent = date(2026, 7, 6)
    result = due_on_for_email(sent, cadence_days=3)
    assert result == date(2026, 7, 9)   # Thursday


def test_due_on_for_email_skips_weekend():
    # Sent Thursday; 3 bd = Tuesday (skips Sat + Sun)
    thursday = date(2026, 7, 9)
    result = due_on_for_email(thursday, cadence_days=3)
    assert result == date(2026, 7, 14)  # Tuesday


def test_due_on_is_never_weekend():
    """due_on_for_email should never land on Saturday or Sunday."""
    for day_offset in range(14):
        start = date(2026, 7, 1)
        from datetime import timedelta
        start = start + timedelta(days=day_offset)
        for n in range(1, 8):
            result = due_on_for_email(start, n)
            assert result.weekday() < 5, (
                f"due_on_for_email({start}, {n}) = {result} is a weekend!"
            )
