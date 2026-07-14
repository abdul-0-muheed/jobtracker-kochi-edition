"""
services/matching.py — Fuzzy company-name matching using rapidfuzz.

match_company(name, companies) returns (Company, score) or None if below threshold.
Scores < AUTO_THRESHOLD are queued as ambiguous for manual confirmation.
"""
from __future__ import annotations

from typing import Optional
from rapidfuzz import fuzz, process


AUTO_THRESHOLD   = 85   # score >= this → auto-link
REVIEW_THRESHOLD = 60   # score between REVIEW and AUTO → queue for review


def _normalize(name: str) -> str:
    """Lowercase, strip common suffixes and punctuation for better matching."""
    import re
    name = name.lower().strip()
    # Remove common suffixes
    for suffix in (" pvt ltd", " pvt. ltd.", " private limited", " limited",
                   " inc", " llc", " corp", " co.", " & co", " technologies",
                   " tech", " solutions", " software", " systems"):
        name = name.removesuffix(suffix)
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def match_company(
    name: str,
    companies: list,          # list of Company model instances
    threshold: int = AUTO_THRESHOLD,
) -> Optional[tuple]:
    """
    Find the best matching Company for a given name string.

    Returns:
        (Company, score)  — if score >= threshold
        None              — if no match is confident enough
    """
    if not companies or not name:
        return None

    norm_name = _normalize(name)
    choices = {c.id: _normalize(c.name) for c in companies}

    # Use WRatio for partial/transposition tolerance
    best = process.extractOne(
        norm_name,
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=REVIEW_THRESHOLD,
    )

    if best is None:
        return None

    matched_id = best[2]
    score = best[1]

    company = next((c for c in companies if c.id == matched_id), None)
    if company is None:
        return None

    if score >= threshold:
        return company, score
    return None  # In REVIEW zone → caller handles queuing


def match_company_with_review(
    name: str,
    companies: list,
) -> dict:
    """
    Returns a dict with keys:
      - 'auto'    : (Company, score) or None
      - 'review'  : list of (Company, score) — candidates for manual review
    """
    if not companies or not name:
        return {"auto": None, "review": []}

    norm_name = _normalize(name)
    choices = {c.id: _normalize(c.name) for c in companies}

    results = process.extract(
        norm_name,
        choices,
        scorer=fuzz.WRatio,
        limit=5,
        score_cutoff=REVIEW_THRESHOLD,
    )

    auto_match = None
    review_candidates = []

    for _matched_val, score, matched_id in results:
        company = next((c for c in companies if c.id == matched_id), None)
        if company is None:
            continue
        if score >= AUTO_THRESHOLD:
            if auto_match is None or score > auto_match[1]:
                auto_match = (company, score)
        else:
            review_candidates.append((company, score))

    return {"auto": auto_match, "review": review_candidates}
