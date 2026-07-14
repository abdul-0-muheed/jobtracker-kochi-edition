"""
tests/test_parser.py — Unit tests for services/spreadsheet_parser.py
"""
import io
import pytest
import openpyxl
from pathlib import Path
from services.spreadsheet_parser import (
    parse_xlsx, _null_if_unknown, _to_bool, _normalize_email,
    _normalize_url, _normalize_match_score, _normalize_company_type,
)


# ── Helper: build a minimal XLSX in memory ────────────────────────────────────

def _make_xlsx(headers: list, rows: list[list]) -> Path:
    """Write an in-memory xlsx to a temp Path and return it."""
    import tempfile
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = Path(f.name)
    wb.save(str(path))
    wb.close()
    return path


# ── _null_if_unknown ──────────────────────────────────────────────────────────

def test_null_if_unknown_returns_none_for_unknown():
    assert _null_if_unknown("Unknown") is None
    assert _null_if_unknown("unknown") is None
    assert _null_if_unknown("  UNKNOWN  ") is None

def test_null_if_unknown_returns_none_for_empty():
    assert _null_if_unknown("") is None
    assert _null_if_unknown(None) is None
    assert _null_if_unknown("   ") is None

def test_null_if_unknown_preserves_valid():
    assert _null_if_unknown("Acme Corp") == "Acme Corp"
    assert _null_if_unknown("123") == "123"


# ── _to_bool ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("Yes",  True),
    ("yes",  True),
    ("YES",  True),
    ("No",   False),
    ("no",   False),
    (None,   False),
    ("Unknown", False),
    ("1",    True),
])
def test_to_bool(val, expected):
    assert _to_bool(val) == expected


# ── _normalize_email ──────────────────────────────────────────────────────────

def test_normalize_email_valid():
    assert _normalize_email("HR@Company.COM") == "hr@company.com"

def test_normalize_email_invalid():
    assert _normalize_email("not-an-email") is None

def test_normalize_email_unknown():
    assert _normalize_email("Unknown") is None

def test_normalize_email_none():
    assert _normalize_email(None) is None


# ── _normalize_match_score ────────────────────────────────────────────────────

def test_match_score_normal():
    assert _normalize_match_score("85") == 85

def test_match_score_float():
    assert _normalize_match_score("92.5") == 92

def test_match_score_clamps_high():
    assert _normalize_match_score("150") == 100

def test_match_score_clamps_low():
    assert _normalize_match_score("-10") == 0

def test_match_score_invalid():
    assert _normalize_match_score("N/A") is None

def test_match_score_none():
    assert _normalize_match_score(None) is None


# ── _normalize_company_type ───────────────────────────────────────────────────

def test_company_type_startup():
    assert _normalize_company_type("Startup") == "startup"
    assert _normalize_company_type("early-stage startup") == "startup"

def test_company_type_mnc():
    assert _normalize_company_type("MNC") == "mnc"
    assert _normalize_company_type("Large Corporation") == "mnc"

def test_company_type_unknown():
    assert _normalize_company_type("other") == "unknown"

def test_company_type_none():
    assert _normalize_company_type(None) is None


# ── parse_xlsx integration ────────────────────────────────────────────────────

def test_parse_xlsx_basic():
    headers = ["Company Name", "Industry", "Match Score (0-100)", "Uses React (Yes/No)"]
    rows = [
        ["Acme Corp", "SaaS", "87", "Yes"],
        ["Beta Ltd",  "AI",   "72", "No"],
    ]
    path = _make_xlsx(headers, rows)
    try:
        result, warnings = parse_xlsx(path)
        assert len(result) == 2
        assert result[0]["name"] == "Acme Corp"
        assert result[0]["match_score"] == 87
        assert result[0]["uses_react"] is True
        assert result[1]["match_score"] == 72
        assert result[1]["uses_react"] is False
    finally:
        path.unlink()


def test_parse_xlsx_unknown_cells_become_none():
    headers = ["Company Name", "HR Email (Public Only)", "Founder / CEO"]
    rows = [["Test Co", "Unknown", "Unknown"]]
    path = _make_xlsx(headers, rows)
    try:
        result, _ = parse_xlsx(path)
        assert result[0]["hr_email"] is None
        assert result[0]["founder_ceo"] is None
    finally:
        path.unlink()


def test_parse_xlsx_missing_required_raises():
    headers = ["Industry", "Match Score"]
    rows = [["SaaS", "85"]]
    path = _make_xlsx(headers, rows)
    try:
        with pytest.raises(ValueError, match="Missing required column"):
            parse_xlsx(path)
    finally:
        import gc; gc.collect()
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows sometimes holds the file; acceptable in CI


def test_parse_xlsx_extra_columns_warned():
    headers = ["Company Name", "Extra Column XYZ"]
    rows = [["Test Co", "some value"]]
    path = _make_xlsx(headers, rows)
    try:
        result, warnings = parse_xlsx(path)
        assert len(result) == 1
        assert any("Extra Column XYZ" in w for w in warnings)
    finally:
        path.unlink()


def test_parse_xlsx_dedup_skips_empty_names():
    headers = ["Company Name", "Industry"]
    rows = [["Acme", "SaaS"], ["", "AI"], ["Unknown", "AI"]]
    path = _make_xlsx(headers, rows)
    try:
        result, _ = parse_xlsx(path)
        # Empty and "Unknown" names should be skipped
        assert len(result) == 1
        assert result[0]["name"] == "Acme"
    finally:
        path.unlink()
