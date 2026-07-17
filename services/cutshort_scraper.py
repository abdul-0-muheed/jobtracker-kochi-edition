"""
cutshort_scraper.py — Scrapes Cutshort.io using their public search API.
Cutshort has an API that returns JSON results.
"""
import logging
import httpx
import urllib.parse

log = logging.getLogger(__name__)


def scrape_cutshort(keyword: str, location: str) -> list:
    """Scrape Cutshort.io for startup jobs via their API."""
    jobs = []
    loc = location.split(",")[0].strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://cutshort.io/",
        "Origin": "https://cutshort.io",
    }
    
    # Cutshort public search API
    api_url = "https://cutshort.io/api/public/jobs/search"
    
    params = {
        "q": keyword,
        "city": loc,
        "minExp": 0,
        "maxExp": 2,
        "pageNo": 1,
        "size": 20
    }
    
    try:
        resp = httpx.get(api_url, params=params, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            job_list = data.get("data", {}).get("jobs", []) or data.get("jobs", []) or data.get("data", [])
            
            for j in job_list:
                if not isinstance(j, dict):
                    continue
                slug = j.get("slug") or j.get("id", "")
                url = f"https://cutshort.io/job/{slug}" if slug else "https://cutshort.io/jobs"
                company_info = j.get("company", {}) or {}
                company_name = company_info.get("name") if isinstance(company_info, dict) else str(company_info)
                
                jobs.append({
                    "title": j.get("title", j.get("designation", "")),
                    "company": company_name or "Cutshort Startup",
                    "location": j.get("city", loc),
                    "url": url,
                    "posted_date": j.get("updatedAt", j.get("postedAt", "")),
                    "source": "Cutshort",
                    "company_type": "Startup"
                })
        else:
            log.warning(f"Cutshort API returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.error(f"Cutshort scrape failed: {e}")

    return jobs
