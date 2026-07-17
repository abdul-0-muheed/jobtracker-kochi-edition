"""
services/career_scraper.py — Career page job scraping (rewritten v2).

Strategy:
  1. Try httpx + BeautifulSoup4 (fast, lightweight)
  2. ATS-specific parsers for 13+ platforms: Greenhouse, Lever, Workday, Ashby,
     BambooHR, Freshteam, SmartRecruiters, Workable, Recruitee, Teamtailor,
     Personio, iCIMS, Breezy HR, JazzHR
  3. Generic HTML job extraction with heuristics (avoids nav/menu text)
  4. If page is a JS SPA (< 800 chars body text or very few links), fall back to
     Playwright headless render with scroll + wait for job elements
  5. Auto-detect ATS platform from final redirect URL
  6. Try ALL ATS parsers as embedded widget fallback
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

log = logging.getLogger(__name__)

RATE_LIMIT_DELAY = (3, 6)

# ── Domain-level SPA flag cache ───────────────────────────────────────────────
_SPA_DOMAINS: set[str] = set()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Job title keywords — expanded to cover more common roles
_JOB_KEYWORDS = re.compile(
    r"\b(engineer|developer|designer|manager|analyst|intern|lead|architect|"
    r"scientist|devops|frontend|backend|fullstack|full.stack|qa|tester|"
    r"consultant|officer|executive|coordinator|specialist|associate|"
    r"programmer|coder|data.scientist|ml.engineer|ai.engineer|react|python|"
    r"java|node|flutter|android|ios|mobile|cloud|security|devrel|sre|"
    r"technical.writer|product.manager|scrum.master|agile.coach|"
    r"recruiter|talent|hr|human.resource|sales|marketing|support|"
    r"graphic|ui|ux|content|writer|copywriter|finance|accountant|"
    r"operations|embedded|firmware|hardware|network|system|infrastructure|"
    r"product|growth|seo|paid.media|digital.marketing|business.development|"
    r"account.manager|project.manager|delivery.manager|customer.success|"
    r"technical.support|helpdesk|administrator|database|dba|etl|"
    r"data.engineer|data.analyst|data.architect|bi|tableau|power.bi|"
    r"openings|position|vacancy|role|hiring)\b",
    re.IGNORECASE,
)

# Noise patterns — only block exact full-string noise phrases (using match not search)
_NOISE_PATTERNS = re.compile(
    r"^(cookie policy|privacy policy|terms of service|sign in|log in|register|"
    r"subscribe|newsletter|copyright|all rights reserved|menu|navigation|"
    r"our team|about us|contact us|follow us|learn more|read more|"
    r"see more|view all|load more|apply now)$",
    re.IGNORECASE,
)

# ATS platform detection by URL patterns
_ATS_URL_PATTERNS = {
    "greenhouse":      re.compile(r"greenhouse\.io|boards\.greenhouse\.io"),
    "lever":           re.compile(r"lever\.co|jobs\.lever\.co"),
    "workday":         re.compile(r"workday\.com|myworkdayjobs\.com"),
    "ashby":           re.compile(r"ashbyhq\.com"),
    "bamboohr":        re.compile(r"bamboohr\.com"),
    "freshteam":       re.compile(r"freshteam\.com|freshworks\.com"),
    "smartrecruiters": re.compile(r"smartrecruiters\.com"),
    "workable":        re.compile(r"workable\.com|apply\.workable\.com"),
    "recruitee":       re.compile(r"recruitee\.com"),
    "teamtailor":      re.compile(r"teamtailor\.com|career\.teamtailor"),
    "personio":        re.compile(r"personio\.com|personio\.de"),
    "icims":           re.compile(r"icims\.com"),
    "breezyhr":        re.compile(r"breezy\.hr|app\.breezy\.hr"),
    "jazzhr":          re.compile(r"jazz\.co|hire\.jazz\.co"),
}


def _get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _abs_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    return urljoin(base_url, href)


def _check_robots(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True


def _detect_ats_platform(url: str) -> str | None:
    """Detect the ATS platform from a URL."""
    for platform, pattern in _ATS_URL_PATTERNS.items():
        if pattern.search(url):
            return platform
    return None


# ── ATS API Fetchers ──────────────────────────────────────────────────────────

def _fetch_greenhouse_api(client_token: str, base_url: str) -> list[dict]:
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{client_token}/jobs?content=true"
    jobs = []
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": _HEADERS["User-Agent"]}) as client:
            resp = client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                for job in data.get("jobs", []):
                    title = job.get("title")
                    url = job.get("absolute_url")
                    loc = job.get("location", {}).get("name", "")
                    date_posted = job.get("updated_at", "")
                    if title and url:
                        jobs.append({"title": title, "location": loc, "url": url, "source": "greenhouse_api", "posted_date": date_posted})
                log.info(f"Greenhouse API: {len(jobs)} jobs found for {client_token}")
    except Exception as e:
        log.warning(f"Greenhouse API failed for {client_token}: {e}")
    return jobs

def _fetch_lever_api(client_token: str, base_url: str) -> list[dict]:
    api_url = f"https://api.lever.co/v0/postings/{client_token}?mode=json"
    jobs = []
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": _HEADERS["User-Agent"]}) as client:
            resp = client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                for job in data:
                    title = job.get("text")
                    url = job.get("hostedUrl")
                    loc = job.get("categories", {}).get("location", "")
                    
                    # Convert ms timestamp to iso
                    created_at = job.get("createdAt")
                    date_posted = ""
                    if created_at:
                        try:
                            date_posted = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat()
                        except Exception:
                            pass
                            
                    if title and url:
                        jobs.append({"title": title, "location": loc, "url": url, "source": "lever_api", "posted_date": date_posted})
                log.info(f"Lever API: {len(jobs)} jobs found for {client_token}")
    except Exception as e:
        log.warning(f"Lever API failed for {client_token}: {e}")
    return jobs

def _fetch_ashby_api(client_token: str, base_url: str) -> list[dict]:
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{client_token}?includeCompensation=true"
    jobs = []
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": _HEADERS["User-Agent"]}) as client:
            resp = client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                for job in data.get("jobs", []):
                    title = job.get("title")
                    url = job.get("jobUrl")
                    loc = job.get("location", "")
                    date_posted = job.get("publishedAt", "")
                    if title and url:
                        jobs.append({"title": title, "location": loc, "url": url, "source": "ashby_api", "posted_date": date_posted})
                log.info(f"Ashby API: {len(jobs)} jobs found for {client_token}")
    except Exception as e:
        log.warning(f"Ashby API failed for {client_token}: {e}")
    return jobs


# ── ATS-specific HTML parsers ─────────────────────────────────────────────────

def _parse_greenhouse(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    # boards.greenhouse.io layout
    for section in soup.find_all("section", class_=re.compile("level-0")):
        dept = section.find(class_=re.compile("section-header"))
        for item in section.find_all("div", class_=re.compile("opening")):
            link = item.find("a", href=True)
            title = link.get_text(strip=True) if link else ""
            url = _abs_url(link["href"] if link else "", base_url)
            loc_el = item.find(class_=re.compile("location"))
            location = loc_el.get_text(strip=True) if loc_el else ""
            if title:
                jobs.append({"title": title, "location": location, "url": url, "source": "greenhouse"})
    # Fallback: simpler greenhouse layout
    if not jobs:
        for item in soup.find_all("div", class_=re.compile("opening")):
            link = item.find("a", href=True)
            title = link.get_text(strip=True) if link else ""
            url = _abs_url(link["href"] if link else "", base_url)
            if title:
                jobs.append({"title": title, "location": "", "url": url, "source": "greenhouse"})
    # Table row variant
    if not jobs:
        for row in soup.find_all("tr"):
            link = row.find("a", href=re.compile(r"/jobs/"))
            if link:
                title = link.get_text(strip=True)
                url = _abs_url(link["href"], base_url)
                if title:
                    jobs.append({"title": title, "location": "", "url": url, "source": "greenhouse"})
    return jobs


def _parse_lever(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all(["div", "li"], class_=re.compile(r"posting$|posting\s")):
        title_el = (item.find(class_=re.compile("posting-name"))
                    or item.find("h5") or item.find("h4") or item.find("h3"))
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        loc_el = item.find(class_=re.compile("location|workplace"))
        location = loc_el.get_text(strip=True) if loc_el else ""
        if title:
            jobs.append({"title": title, "location": location, "url": url, "source": "lever"})
    return jobs


def _parse_workday(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all(attrs={"data-automation-id": re.compile("jobTitle|job-title")}):
        title = item.get_text(strip=True)
        parent_link = item.find_parent("a", href=True) or item.find("a", href=True)
        url = _abs_url(parent_link["href"] if parent_link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "workday"})
    return jobs


def _parse_ashby(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all("a", href=re.compile(r"/jobs/")):
        title = item.get_text(strip=True)
        url = _abs_url(item["href"], base_url)
        if title and len(title) < 100:
            jobs.append({"title": title, "location": "", "url": url, "source": "ashby"})
    return jobs


def _parse_bamboohr(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all(class_=re.compile("BambooHR-ATS-board-item|BambooHR-ATS-jobs-item")):
        title_el = item.find(class_=re.compile("BambooHR-ATS-board-btn|BambooHR-ATS-job-title"))
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "bamboohr"})
    return jobs


def _parse_freshteam(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all(class_=re.compile("job.?listing|job.?item|job.?card", re.I)):
        title_el = item.find(["h2", "h3", "h4", "a"])
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title and _JOB_KEYWORDS.search(title):
            jobs.append({"title": title, "location": "", "url": url, "source": "freshteam"})
    return jobs


def _parse_smartrecruiters(soup: BeautifulSoup, base_url: str) -> list[dict]:
    jobs = []
    for item in soup.find_all("li", class_=re.compile("job-item|opening-job")):
        title_el = item.find(class_=re.compile("job-title|opening-job-title"))
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "smartrecruiters"})
    return jobs


def _parse_workable(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse Workable ATS job boards."""
    jobs = []
    for item in soup.find_all(["li", "article"], class_=re.compile(r"jobs-board__item|job\b")):
        title_el = item.find(class_=re.compile(r"job-title|title")) or item.find(["h2", "h3", "h4"])
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        loc_el = item.find(class_=re.compile(r"location|city"))
        location = loc_el.get_text(strip=True) if loc_el else ""
        if title:
            jobs.append({"title": title, "location": location, "url": url, "source": "workable"})
    if not jobs:
        for span in soup.find_all("span", class_=re.compile("job-title")):
            title = span.get_text(strip=True)
            link = span.find_parent("a", href=True)
            url = _abs_url(link["href"] if link else "", base_url)
            if title:
                jobs.append({"title": title, "location": "", "url": url, "source": "workable"})
    return jobs


def _parse_recruitee(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse Recruitee ATS job boards."""
    jobs = []
    for item in soup.find_all(["li", "div"], class_=re.compile(r"job-offers__item|offer")):
        title_el = item.find(class_=re.compile(r"job-title|offer__title")) or item.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "recruitee"})
    return jobs


def _parse_teamtailor(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse Teamtailor ATS job boards."""
    jobs = []
    for item in soup.find_all(["li", "article"], class_=re.compile(r"\bjob\b|\bposition\b")):
        title_el = item.find(class_=re.compile(r"title")) or item.find(["h2", "h3", "h4"])
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        loc_el = item.find(class_=re.compile(r"location"))
        location = loc_el.get_text(strip=True) if loc_el else ""
        if title:
            jobs.append({"title": title, "location": location, "url": url, "source": "teamtailor"})
    for a in soup.find_all("a", attrs={"data-job": True}):
        title = a.get_text(strip=True)
        url = _abs_url(a.get("href", ""), base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "teamtailor"})
    return jobs


def _parse_personio(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse Personio ATS job boards."""
    jobs = []
    for item in soup.find_all(class_=re.compile(r"job-widget-job-title|position-list-item")):
        title = item.get_text(strip=True)
        link = item.find_parent("a", href=True) or item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "personio"})
    if not jobs:
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if cells:
                title = cells[0].get_text(strip=True)
                link = row.find("a", href=True)
                url = _abs_url(link["href"] if link else "", base_url)
                if title and _JOB_KEYWORDS.search(title):
                    jobs.append({"title": title, "location": "", "url": url, "source": "personio"})
    return jobs


def _parse_icims(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse iCIMS ATS job boards."""
    jobs = []
    for item in soup.find_all(class_=re.compile(r"iCIMS_JobTitle|icims_JobTitle")):
        title = item.get_text(strip=True)
        link = item.find("a", href=True) or item.find_parent("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "icims"})
    if not jobs:
        for row in soup.find_all("tr", class_=re.compile(r"iCIMS_JobsTable")):
            link = row.find("a", href=True)
            title = link.get_text(strip=True) if link else ""
            url = _abs_url(link["href"] if link else "", base_url)
            if title:
                jobs.append({"title": title, "location": "", "url": url, "source": "icims"})
    return jobs


def _parse_breezyhr(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse Breezy HR ATS job boards."""
    jobs = []
    for item in soup.find_all(class_=re.compile(r"\bposition\b")):
        title_el = item.find(["h2", "h3"]) or item.find(class_=re.compile(r"title|name"))
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "breezyhr"})
    return jobs


def _parse_jazzhr(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse JazzHR ATS job boards."""
    jobs = []
    for item in soup.find_all(["div", "li"], class_=re.compile(r"job.?listing|resumator.?job")):
        title_el = item.find(["h3", "h4", "a"])
        title = title_el.get_text(strip=True) if title_el else ""
        link = item.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)
        if title:
            jobs.append({"title": title, "location": "", "url": url, "source": "jazzhr"})
    return jobs


# ── Generic extractor ─────────────────────────────────────────────────────────

def _extract_jobs_static(html: str, base_url: str) -> list[dict]:
    """Extract job listings from static HTML with heuristics."""
    soup = BeautifulSoup(html, "lxml")

    # Remove noisy structural elements
    for tag in soup.find_all(["nav", "footer", "header", "script", "style",
                               "noscript", "aside", "form"]):
        tag.decompose()

    # Detect ATS platform from URL
    platform = _detect_ats_platform(base_url)

    # ATS-specific parsers by detected platform
    _ATS_PARSERS = {
        "greenhouse":      _parse_greenhouse,
        "lever":           _parse_lever,
        "workday":         _parse_workday,
        "ashby":           _parse_ashby,
        "bamboohr":        _parse_bamboohr,
        "freshteam":       _parse_freshteam,
        "smartrecruiters": _parse_smartrecruiters,
        "workable":        _parse_workable,
        "recruitee":       _parse_recruitee,
        "teamtailor":      _parse_teamtailor,
        "personio":        _parse_personio,
        "icims":           _parse_icims,
        "breezyhr":        _parse_breezyhr,
        "jazzhr":          _parse_jazzhr,
    }

    if platform and platform in _ATS_PARSERS:
        jobs = _ATS_PARSERS[platform](soup, base_url)
        if jobs:
            return jobs

    # Try ALL ATS parsers (catches embedded widgets on company career pages)
    for name, parser_fn in _ATS_PARSERS.items():
        try:
            jobs = parser_fn(soup, base_url)
            if jobs:
                log.info(f"ATS widget detected via {name} parser")
                return jobs
        except Exception:
            pass

    # Try JSON-LD job postings (most reliable generic method)
    jobs = _extract_json_ld_jobs(soup, base_url)
    if jobs:
        return jobs

    # Generic: find elements with job-like class names
    jobs = _extract_by_class_heuristic(soup, base_url)
    if jobs:
        return jobs

    # Final fallback: anchor-based extraction
    return _extract_job_links(soup, base_url)


def _extract_json_ld_jobs(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Extract JobPosting from JSON-LD structured data — very reliable."""
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and data.get("@graph"):
                items = data["@graph"]
            else:
                items = [data]
            for item in items:
                if item.get("@type") in ("JobPosting", "jobPosting"):
                    title = item.get("title") or item.get("name", "")
                    location_data = item.get("jobLocation", {})
                    if isinstance(location_data, list):
                        location_data = location_data[0] if location_data else {}
                    if isinstance(location_data, dict):
                        addr = location_data.get("address", {})
                        location = addr.get("addressLocality", "") if isinstance(addr, dict) else str(addr)
                    else:
                        location = ""
                    url = item.get("url", base_url)
                    date_posted = item.get("datePosted", "")
                    valid_through = item.get("validThrough", "")
                    if title:
                        jobs.append({
                            "title": title, "location": location, "url": url, 
                            "source": "json_ld", "posted_date": date_posted, "deadline": valid_through
                        })
        except Exception:
            pass
    return jobs

def _extract_deadline(elem: BeautifulSoup) -> str:
    """Extract an application deadline from a job listing element using text heuristics."""
    text = elem.get_text(separator=" ", strip=True)
    # Match phrases like "Deadline: Oct 12", "Closes: 2024-12-01", "Apply by 15th Jan"
    match = re.search(r'(?:deadline|closes|closing date|apply by)\s*:?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})', text, re.IGNORECASE)
    if match:
        try:
            d = date_parser.parse(match.group(1))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except Exception:
            pass
    return ""


def _extract_date(elem: BeautifulSoup) -> str:
    """Extract a date from a job listing element."""
    # 1. Check <time> tags
    for time_tag in elem.find_all("time"):
        dt = time_tag.get("datetime")
        if dt:
            try:
                parsed = date_parser.parse(dt)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.isoformat()
            except Exception:
                pass
        
    text = elem.get_text(separator=" ", strip=True)
    
    # 2. Relative dates
    rel_match = re.search(r'(\d+)\s*(day|week|month|year|hr|hour|min)s?\s*ago', text, re.IGNORECASE)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        now = datetime.now(timezone.utc)
        if 'day' in unit:
            d = now - timedelta(days=val)
        elif 'week' in unit:
            d = now - timedelta(weeks=val)
        elif 'month' in unit:
            d = now - timedelta(days=val*30)
        elif 'year' in unit:
            d = now - timedelta(days=val*365)
        else:
            d = now
        return d.isoformat()
        
    if re.search(r'\byesterday\b', text, re.IGNORECASE):
        return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if re.search(r'\btoday\b', text, re.IGNORECASE):
        return datetime.now(timezone.utc).isoformat()
        
    # 3. Explicit dates preceded by keywords
    date_match = re.search(r'(?:posted|published|date)\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})', text, re.IGNORECASE)
    if date_match:
        try:
            d = date_parser.parse(date_match.group(1))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except Exception:
            pass
            
    return ""

def _extract_by_class_heuristic(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Find elements with class names suggesting job listings."""
    JOB_CLASS = re.compile(
        r"job.?(card|item|listing|post|row|entry|result|position|opening|vacancy|role)|"
        r"(position|opening|vacancy|role).?(card|item|list|row|entry)",
        re.IGNORECASE,
    )
    jobs = []
    seen = set()
    for elem in soup.find_all(True, class_=JOB_CLASS, limit=300):
        title_el = (elem.find(["h1", "h2", "h3", "h4", "h5"]) or
                    elem.find("a", href=True) or
                    elem.find("strong") or
                    elem.find("b"))
        title = title_el.get_text(separator=" ", strip=True) if title_el else ""
        title = re.sub(r"\s+", " ", title).strip()

        if not title or len(title) > 120 or len(title) < 4:
            continue
        if _NOISE_PATTERNS.match(title):   # exact match only
            continue
        if not _JOB_KEYWORDS.search(title):
            continue
        if title in seen:
            continue
        seen.add(title)

        link = elem.find("a", href=True)
        url = _abs_url(link["href"] if link else "", base_url)

        loc_el = elem.find(class_=re.compile(r"location|city|place|region", re.I))
        location = loc_el.get_text(strip=True)[:80] if loc_el else ""

        posted_date = _extract_date(elem)
        deadline = _extract_deadline(elem)

        jobs.append({"title": title, "location": location, "url": url, "source": "career_page", "posted_date": posted_date, "deadline": deadline})

    return jobs[:50]


def _extract_job_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Extract job links by finding anchors whose text looks like a job title.
    URL filter is relaxed — only block links pointing to unrelated external domains."""
    jobs = []
    seen = set()
    base_domain = _get_domain(base_url)

    for a in soup.find_all("a", href=True, limit=500):
        title = a.get_text(separator=" ", strip=True)
        title = re.sub(r"\s+", " ", title).strip()

        if not title or len(title) > 100 or len(title) < 5:
            continue
        if not _JOB_KEYWORDS.search(title):
            continue
        if _NOISE_PATTERNS.match(title):
            continue
        if title in seen:
            continue
        seen.add(title)

        url = _abs_url(a["href"], base_url)

        # Allow same-domain links freely; for other domains require job-related URL
        if url:
            url_domain = _get_domain(url)
            known_ats = any(p.search(url) for p in _ATS_URL_PATTERNS.values())
            if not known_ats and url_domain and url_domain != base_domain:
                if not any(kw in url.lower() for kw in [
                    "job", "career", "opening", "position", "vacancy",
                    "role", "posting", "work", "apply", "hiring", "recruit"
                ]):
                    continue

        # Look at the parent element to extract date
        parent = a.find_parent(["li", "tr", "div", "article"])
        posted_date = _extract_date(parent) if parent else ""
        deadline = _extract_deadline(parent) if parent else ""

        jobs.append({"title": title, "location": "", "url": url, "source": "career_page", "posted_date": posted_date, "deadline": deadline})

    return jobs[:30]


# ── SPA detection ─────────────────────────────────────────────────────────────

def _looks_like_spa(html: str) -> bool:
    """
    Detect if a page is a JS SPA needing Playwright.
    Threshold raised from 300 → 800 chars; also detects by very few links.
    """
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(separator=" ", strip=True)
    root_div = soup.find("div", id=re.compile(r"^(root|app|__next|__nuxt|ember|gatsby-focus-wrapper)$"))
    links = soup.find_all("a", href=True)

    if len(body_text) < 800 and root_div is not None:
        return True
    if len(body_text) < 500 and len(links) < 5:
        return True
    return False


def _scrape_with_playwright(url: str, wait_extra: int = 5) -> list[dict]:
    """Render JS-heavy SPA pages with Playwright and extract jobs."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_HEADERS["User-Agent"])
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                except Exception:
                    log.warning(f"Playwright could not load {url}")
                    browser.close()
                    return []

            # Wait for common job list selectors to appear
            job_selectors = [
                ".job-card", ".job-listing", ".opening", ".position",
                "[class*='job']", "[class*='career']", "[class*='opening']",
                "li[class*='job']", "article[class*='job']",
            ]
            for sel in job_selectors:
                try:
                    page.wait_for_selector(sel, timeout=3_000)
                    break
                except Exception:
                    pass

            # Multiple scroll passes to trigger lazy loading
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

            time.sleep(wait_extra)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            html = page.content()
            browser.close()

        jobs = _extract_jobs_static(html, url)
        log.info(f"Playwright extracted {len(jobs)} jobs from {url}")
        return jobs
    except Exception as e:
        log.warning(f"Playwright fallback failed for {url}: {e}")
        return []


# ── Main entry point ──────────────────────────────────────────────────────────

def _extract_ats_token(url: str, platform: str) -> str | None:
    """Extract the client token from an ATS URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    
    if platform == "greenhouse":
        # boards.greenhouse.io/token or greenhouse.io/careers/token
        if parsed.netloc == "boards.greenhouse.io" and len(parts) > 0:
            return parts[0]
    elif platform == "lever":
        # jobs.lever.co/token
        if parsed.netloc == "jobs.lever.co" and len(parts) > 0:
            return parts[0]
    elif platform == "ashby":
        # jobs.ashbyhq.com/token
        if parsed.netloc == "jobs.ashbyhq.com" and len(parts) > 0:
            return parts[0]
    return None

def scrape_career_page(url: str, delay: tuple = RATE_LIMIT_DELAY) -> list[dict]:
    """
    Scrape a company career page for job listings.
    Returns list of {title, location, url, source, posted_date}.
    """
    if not url:
        return []

    time.sleep(random.uniform(*delay))
    domain = _get_domain(url)

    if not _check_robots(url):
        log.info(f"robots.txt disallows scraping {url}")
        return []

    # Fast-path: try ATS JSON APIs if direct ATS board URL is provided
    platform = _detect_ats_platform(url)
    if platform in ["greenhouse", "lever", "ashby"]:
        token = _extract_ats_token(url, platform)
        if token:
            log.info(f"Fast-path API extraction for {platform} with token '{token}'")
            if platform == "greenhouse":
                jobs = _fetch_greenhouse_api(token, url)
            elif platform == "lever":
                jobs = _fetch_lever_api(token, url)
            elif platform == "ashby":
                jobs = _fetch_ashby_api(token, url)
                
            if jobs:
                return jobs

    if domain in _SPA_DOMAINS:
        return _scrape_with_playwright(url)

    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
            final_url = str(resp.url)  # URL after redirects
    except httpx.HTTPStatusError as e:
        log.warning(f"HTTP {e.response.status_code} for {url}")
        return []
    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return []

    # Log if we were redirected to an ATS platform
    if final_url != url:
        log.info(f"Redirected: {url} → {final_url}")
        new_platform = _detect_ats_platform(final_url)
        if new_platform:
            log.info(f"Detected ATS platform via redirect: {new_platform}")
            # Try API extraction on the redirected URL!
            if new_platform in ["greenhouse", "lever", "ashby"]:
                token = _extract_ats_token(final_url, new_platform)
                if token:
                    if new_platform == "greenhouse":
                        jobs = _fetch_greenhouse_api(token, final_url)
                    elif new_platform == "lever":
                        jobs = _fetch_lever_api(token, final_url)
                    elif new_platform == "ashby":
                        jobs = _fetch_ashby_api(token, final_url)
                    if jobs:
                        return jobs

    if _looks_like_spa(html):
        log.info(f"{url} looks like a SPA — switching to Playwright")
        _SPA_DOMAINS.add(domain)
        return _scrape_with_playwright(final_url)

    jobs = _extract_jobs_static(html, final_url)
    log.info(f"Found {len(jobs)} job(s) at {url}")
    return jobs
