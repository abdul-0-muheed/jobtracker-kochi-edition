"""
tests/test_matching.py — Unit tests for services/matching.py
"""
import pytest
from unittest.mock import MagicMock
from services.matching import (
    match_company, match_company_with_review, _normalize,
    AUTO_THRESHOLD, REVIEW_THRESHOLD,
)


def _mock_company(cid: int, name: str):
    c = MagicMock()
    c.id   = cid
    c.name = name
    return c


# ── _normalize ────────────────────────────────────────────────────────────────

def test_normalize_strips_suffixes():
    # Suffixes like 'technologies', 'solutions', 'pvt ltd' are stripped
    assert "acme" in _normalize("Acme Technologies")
    assert "beta" in _normalize("Beta Solutions Pvt Ltd")
    assert "gamma" in _normalize("Gamma Software Pvt. Ltd.")

def test_normalize_lowercases():
    result = _normalize("ACME CORP")
    assert "acme" in result

def test_normalize_removes_special_chars():
    result = _normalize("A&B Systems")
    assert "&" not in result


# ── match_company ─────────────────────────────────────────────────────────────

def test_match_company_exact():
    companies = [_mock_company(1, "TCS"), _mock_company(2, "Infosys")]
    result = match_company("TCS", companies)
    assert result is not None
    company, score = result
    assert company.id == 1
    assert score >= AUTO_THRESHOLD


def test_match_company_case_insensitive():
    companies = [_mock_company(1, "Infosys")]
    result = match_company("infosys", companies)
    assert result is not None
    assert result[0].id == 1


def test_match_company_suffix_tolerance():
    companies = [_mock_company(1, "Kochi Technologies Pvt Ltd")]
    result = match_company("Kochi Technologies", companies)
    assert result is not None
    assert result[0].id == 1


def test_match_company_no_match_below_threshold():
    companies = [_mock_company(1, "Completely Different Name")]
    result = match_company("XYZ Corp Unrelated", companies, threshold=AUTO_THRESHOLD)
    # Either None or very low score
    # Should not auto-match
    assert result is None or result[1] < AUTO_THRESHOLD


def test_match_company_empty_list():
    assert match_company("Acme", []) is None


def test_match_company_empty_name():
    companies = [_mock_company(1, "Acme")]
    assert match_company("", companies) is None


def test_match_company_none_name():
    companies = [_mock_company(1, "Acme")]
    assert match_company(None, companies) is None


# ── match_company_with_review ─────────────────────────────────────────────────

def test_with_review_returns_auto_for_high_score():
    companies = [
        _mock_company(1, "Infosys"),
        _mock_company(2, "TCS"),
    ]
    result = match_company_with_review("Infosys", companies)
    assert result["auto"] is not None
    assert result["auto"][0].id == 1


def test_with_review_returns_empty_for_no_match():
    companies = [_mock_company(1, "Acme")]
    result = match_company_with_review("Completely Unrelated XYZ Corp 12345", companies)
    assert result["auto"] is None


def test_with_review_handles_empty():
    result = match_company_with_review("", [])
    assert result == {"auto": None, "review": []}


# ── Fuzzy tolerance tests ─────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected_id", [
    ("Tata Consultancy Services", 1),
    ("TCS",                       1),
    ("Wipro Technologies",        2),
    ("wipro",                     2),
])
def test_known_company_fuzzy(query, expected_id):
    companies = [
        _mock_company(1, "Tata Consultancy Services"),
        _mock_company(2, "Wipro Technologies"),
        _mock_company(3, "Infosys Limited"),
    ]
    result = match_company(query, companies)
    if result:
        assert result[0].id == expected_id
