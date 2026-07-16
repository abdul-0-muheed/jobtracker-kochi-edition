"""
services/infopark_scraper.py — Scrape job listings from https://infopark.in/companies-job
Uses httpx + BeautifulSoup (already in requirements). No JS rendering needed – jobs are
server-side rendered in a plain HTML table with ?page=N pagination.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://infopark.in/companies-job"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://infopark.in/",
}


def _parse_jobs_from_html(html: str) -> list[dict]:
    """Parse job rows from one page of the Infopark jobs listing HTML."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []

    # Jobs are in a <table> inside the main content; rows have links to /company-jobs/details/
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        link_tag = row.find("a", href=lambda h: h and "/company-jobs/details/" in h)
        if not link_tag:
            continue

        posted_date = cells[0].get_text(strip=True)
        title       = cells[1].get_text(strip=True)
        company     = cells[2].get_text(strip=True)
        last_date   = cells[3].get_text(strip=True)
        href        = link_tag.get("href", "")
        url = href if href.startswith("http") else f"https://infopark.in{href}"

        if title:
            jobs.append({
                "posted_date": posted_date,
                "title":       title,
                "company":     company,
                "last_date":   last_date,
                "url":         url,
            })

    return jobs


def scrape_infopark_jobs(
    search: Optional[str] = None,
    max_pages: int = 5,
    delay: float = 0.8,
) -> list[dict]:
    """
    Scrape jobs from infopark.in/companies-job.

    Args:
        search:    Optional keyword to filter (passed as ?search=...).
        max_pages: Maximum number of pages to scrape (default 5, ~100 jobs).
        delay:     Seconds to wait between page requests.

    Returns:
        List of job dicts with keys: posted_date, title, company, last_date, url.
    """
    all_jobs: list[dict] = []

    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            params: dict[str, str] = {"page": str(page)}
            if search:
                params["search"] = search

            try:
                resp = client.get(BASE_URL, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning(f"Infopark scrape HTTP error on page {page}: {exc}")
                break

            html = resp.text

            # Stop pagination when site says "No Jobs."
            if "No Jobs." in html or "no jobs" in html.lower():
                log.info(f"Infopark: no more jobs at page {page}. Stopping.")
                break

            page_jobs = _parse_jobs_from_html(html)
            if not page_jobs:
                log.info(f"Infopark: empty page {page}. Stopping.")
                break

            log.info(f"Infopark page {page}: {len(page_jobs)} jobs")
            all_jobs.extend(page_jobs)

            if page < max_pages:
                time.sleep(delay)

    log.info(f"Infopark scrape complete: {len(all_jobs)} total jobs")
    return all_jobs


def scrape_intern_jobs(max_pages: int = 10) -> list[dict]:
    """Convenience wrapper to fetch only internship/intern listings."""
    return scrape_infopark_jobs(search="Intern", max_pages=max_pages)
