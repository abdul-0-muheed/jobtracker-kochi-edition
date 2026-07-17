"""
shine_scraper.py — Scrapes Shine.com using their search API.
Shine has a REST API endpoint that returns JSON job data.
"""
import logging
import httpx
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def scrape_shine(keyword: str, location: str) -> list:
    """Scrape Shine.com for jobs."""
    jobs = []
    loc = location.split(",")[0].strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.shine.com/",
    }

    # Shine uses a direct URL slug format: /job-search/keyword-jobs-in-location
    kw_slug = keyword.replace(" ", "-").lower()
    loc_slug = loc.replace(" ", "-").lower()
    url = f"https://www.shine.com/job-search/{kw_slug}-jobs-in-{loc_slug}/"

    try:
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            
            # Shine job cards
            cards = soup.find_all("div", class_=lambda c: c and ("jobCard" in c or "job_card" in c) if c else False)
            if not cards:
                # Alternative: look for article tags or list items with job data
                cards = soup.find_all("article") or soup.find_all("li", class_=lambda c: c and "job" in c.lower() if c else False)

            for card in cards:
                title_el = card.find(["h2", "h3", "h4"]) or card.find("a", class_=lambda c: c and "title" in c.lower() if c else False)
                company_el = card.find(class_=lambda c: c and "company" in c.lower() if c else False)
                loc_el = card.find(class_=lambda c: c and "location" in c.lower() if c else False)
                link_el = card.find("a", href=True)
                date_el = card.find(class_=lambda c: c and "date" in c.lower() if c else False)
                
                if title_el:
                    href = link_el["href"] if link_el else url
                    if href.startswith("/"):
                        href = "https://www.shine.com" + href
                    jobs.append({
                        "title": title_el.get_text(strip=True),
                        "company": company_el.get_text(strip=True) if company_el else "Shine Company",
                        "location": loc_el.get_text(strip=True) if loc_el else loc,
                        "url": href,
                        "posted_date": date_el.get_text(strip=True) if date_el else "",
                        "source": "Shine",
                        "company_type": "IT / Tech"
                    })
        else:
            log.warning(f"Shine returned HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"Shine scrape failed: {e}")

    return jobs
