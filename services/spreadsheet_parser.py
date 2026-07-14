"""
services/spreadsheet_parser.py — Parse the 19-column Kochi companies XLSX.

Implements the column mapping from Appendix A of the PRD.
Returns (rows: list[dict], warnings: list[str]).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl


# ── Column header aliases (case-insensitive, stripped) ─────────────────────────
# Handles BOM prefix (\ufeff) and encoding variants like 0?100 vs 0-100
COLUMN_MAP: dict[str, str] = {
    "company name":                              "name",
    "official website":                          "website",
    "linkedin company page":                     "linkedin_url",
    "career page":                               "career_page_url",
    "hr email (public only)":                    "hr_email",
    "hr email":                                  "hr_email",
    "founder / ceo":                             "founder_ceo",
    "founder/ceo":                               "founder_ceo",
    "founder linkedin":                          "founder_linkedin",
    "location":                                  "location",
    "company size":                              "company_size",
    "startup or mnc":                            "company_type",
    "industry":                                  "industry",
    "tech stack":                                "tech_stack",
    "uses react (yes/no)":                       "uses_react",
    "uses react":                                "uses_react",
    "uses python (yes/no)":                      "uses_python",
    "uses python":                               "uses_python",
    "uses ai (yes/no)":                          "uses_ai",
    "uses ai":                                   "uses_ai",
    "internship friendly":                       "internship_friendly",
    "freshers hiring":                           "freshers_hiring",
    "match score (0-100)":                       "match_score",
    # Actual file has "0?100" which normalises to "0-100" after regex
    "match score (0-100) based on my profile":   "match_score",
    "match score (0?100) based on my profile":   "match_score",
    "match score (0?100)":                       "match_score",
    "match score":                               "match_score",
    "notes":                                     "notes",
    # Extra columns in actual file — intentionally ignored
    "marking":                                   "_ignore",
    "numbers":                                   "_ignore",
}

REQUIRED_COLUMNS = {"name"}

_UNKNOWN_RE = re.compile(r"^\s*unknown\s*$", re.IGNORECASE)
_EMAIL_RE   = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE     = re.compile(r"^https?://", re.IGNORECASE)


def _null_if_unknown(val: Any) -> Any:
    """Return None if value is null-like or 'Unknown'."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or _UNKNOWN_RE.match(s):
        return None
    return s


def _to_bool(val: Any) -> bool:
    if val is None:
        return False
    return str(val).strip().lower() in ("yes", "true", "1")


def _normalize_company_type(val: Any) -> str | None:
    if val is None:
        return None
    v = str(val).strip().lower()
    if "startup" in v:
        return "startup"
    if "mnc" in v or "corporation" in v or "enterprise" in v:
        return "mnc"
    return "unknown"


def _normalize_email(val: Any) -> str | None:
    raw = _null_if_unknown(val)
    if not raw:
        return None
    lower = raw.lower().strip()
    if _EMAIL_RE.match(lower):
        return lower
    return None


def _normalize_url(val: Any) -> str | None:
    raw = _null_if_unknown(val)
    if not raw:
        return None
    if not _URL_RE.match(raw):
        raw = "https://" + raw
    return raw


def _normalize_match_score(val: Any) -> int | None:
    if val is None:
        return None
    try:
        score = int(float(str(val).strip()))
        return max(0, min(100, score))
    except (ValueError, TypeError):
        return None


def _clean_founder(val: Any) -> str | None:
    """Strip leading phrases like "I'm " / "I am " from founder names."""
    raw = _null_if_unknown(val)
    if not raw:
        return None
    # Remove "I'm ", "I am " prefix (case-insensitive)
    cleaned = re.sub(r"(?i)^i\s*(?:am|'m)\s+", "", raw).strip()
    return cleaned or raw


def parse_xlsx(filepath: str | Path) -> tuple[list[dict], list[str]]:
    """
    Parse the Kochi companies XLSX.

    Returns:
        rows     — list of dicts ready for DB insert
        warnings — list of human-readable warning strings
    """
    filepath = Path(filepath)
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    warnings: list[str] = []
    rows_iter = ws.iter_rows(values_only=True)

    # ── Header row ─────────────────────────────────────────────────────────────
    raw_headers = next(rows_iter, None)
    if raw_headers is None:
        raise ValueError("Spreadsheet is empty (no header row found).")

    header_map: dict[int, str] = {}   # col_index → db_field
    seen_unknown: list[str] = []

    for i, h in enumerate(raw_headers):
        if h is None:
            continue
        # Strip BOM (\ufeff) and invisible unicode that Excel adds
        raw_h = str(h).replace('\ufeff', '').replace('\u200b', '').strip()
        key = raw_h.lower()
        # Normalise all non-ASCII hyphens / en-dashes / question-marks → hyphen
        key = re.sub(r'[\u2013\u2014\u2212?]', '-', key)
        if key in COLUMN_MAP:
            db_field = COLUMN_MAP[key]
            if db_field != "_ignore":
                header_map[i] = db_field
            # else: silently skip ignored columns
        else:
            seen_unknown.append(str(h))

    if seen_unknown:
        warnings.append(f"Ignored unknown columns: {', '.join(seen_unknown)}")

    # Check required columns
    mapped_fields = set(header_map.values())
    missing = REQUIRED_COLUMNS - mapped_fields
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(missing)}. "
            "Please ensure the spreadsheet has a 'Company Name' column."
        )

    # ── Data rows ──────────────────────────────────────────────────────────────
    result: list[dict] = []
    for row_num, row in enumerate(rows_iter, start=2):
        raw: dict[str, Any] = {}
        for col_idx, field in header_map.items():
            val = row[col_idx] if col_idx < len(row) else None
            raw[field] = val

        # Skip completely blank rows
        if not any(v for v in raw.values()):
            continue

        # Apply transforms
        record: dict = {}

        record["name"]              = _null_if_unknown(raw.get("name"))
        if not record["name"]:
            warnings.append(f"Row {row_num}: skipped (empty Company Name).")
            continue

        record["website"]           = _normalize_url(raw.get("website"))
        record["linkedin_url"]      = _normalize_url(raw.get("linkedin_url"))
        record["career_page_url"]   = _normalize_url(raw.get("career_page_url"))
        record["hr_email"]          = _normalize_email(raw.get("hr_email"))
        record["founder_ceo"]       = _clean_founder(raw.get("founder_ceo"))
        record["founder_linkedin"]  = _normalize_url(raw.get("founder_linkedin"))
        record["location"]          = _null_if_unknown(raw.get("location"))
        record["company_size"]      = _null_if_unknown(raw.get("company_size"))
        record["company_type"]      = _normalize_company_type(raw.get("company_type"))
        record["industry"]          = _null_if_unknown(raw.get("industry"))
        record["tech_stack"]        = _null_if_unknown(raw.get("tech_stack"))
        record["uses_react"]        = _to_bool(raw.get("uses_react"))
        record["uses_python"]       = _to_bool(raw.get("uses_python"))
        record["uses_ai"]           = _to_bool(raw.get("uses_ai"))
        record["internship_friendly"]= _null_if_unknown(raw.get("internship_friendly"))
        record["freshers_hiring"]   = _null_if_unknown(raw.get("freshers_hiring"))
        record["match_score"]       = _normalize_match_score(raw.get("match_score"))
        record["notes"]             = _null_if_unknown(raw.get("notes"))

        result.append(record)

    wb.close()
    return result, warnings
