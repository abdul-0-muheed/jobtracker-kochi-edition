"""
remoteok_scraper.py — RemoteOK has a public JSON API. No browser required.
"""
import logging
import httpx

log = logging.getLogger(__name__)

SKILL_TAGS = ["javascript", "react", "python", "sql", "fastapi", "nextjs", "node", "typescript", "fullstack", "backend", "frontend"]

def scrape_remoteok(role: str, location: str) -> list:
    """Scrape RemoteOK using their public JSON API."""
    jobs = []
    # Map role keywords to RemoteOK tags
    tag = "javascript"
    role_lower = role.lower()
    if "react" in role_lower:
        tag = "react"
    elif "python" in role_lower or "fastapi" in role_lower:
        tag = "python"
    elif "full stack" in role_lower or "fullstack" in role_lower:
        tag = "fullstack"
    elif "backend" in role_lower:
        tag = "backend"
    elif "node" in role_lower:
        tag = "nodejs"
    elif "frontend" in role_lower:
        tag = "javascript"
    
    url = f"https://remoteok.com/api?tag={tag}"
    
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code != 200:
            log.warning(f"RemoteOK returned status {resp.status_code}")
            return []
        
        data = resp.json()
        # First item is always a legal notice - skip it
        for job in data[1:]:
            if not isinstance(job, dict):
                continue
            title = job.get("position", "")
            company = job.get("company", "")
            url_ = job.get("url", "")
            posted = job.get("date", "")
            if title and company and url_:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": "Remote",
                    "url": url_,
                    "posted_date": posted,
                    "source": "RemoteOK"
                })
    except Exception as e:
        log.error(f"RemoteOK scrape failed: {e}")
    
    return jobs
