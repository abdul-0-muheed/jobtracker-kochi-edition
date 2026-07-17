"""
blueprints/linkedin_scraper.py — Deep scan a company's jobs using LinkedIn's public guest API.
This bypasses fragile company career pages to get highly structured, perfectly dated job listings.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify

from models import Company, Opening, db

log = logging.getLogger(__name__)

linkedin_scraper_bp = Blueprint("linkedin_scraper", __name__, url_prefix="/linkedin_scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

@linkedin_scraper_bp.route("/scan/<int:cid>", methods=["POST"])
def scan_linkedin(cid: int):
    company = Company.query.get_or_404(cid)
    query = urllib.parse.quote(f"{company.name}")
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query}&start=0"
    
    try:
        with httpx.Client(headers=HEADERS, timeout=15) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except Exception as e:
        log.error(f"LinkedIn fetch failed for {company.name}: {e}")
        return jsonify({"error": "Failed to fetch from LinkedIn"}), 500
        
    soup = BeautifulSoup(resp.text, 'lxml')
    job_cards = soup.find_all('li')
    
    now = datetime.now(timezone.utc).isoformat()
    jobs_added = 0
    jobs_updated = 0
    
    for card in job_cards:
        title_elem = card.find('h3', class_='base-search-card__title')
        if not title_elem:
            continue
            
        title = title_elem.get_text(strip=True)
        
        # Location
        loc_elem = card.find('span', class_='job-search-card__location')
        location = loc_elem.get_text(strip=True) if loc_elem else ""
        
        # Link
        link_elem = card.find('a', class_='base-card__full-link')
        job_url = link_elem.get('href', '').split('?')[0] if link_elem else ""
        
        # Date
        date_elem = card.find('time', class_='job-search-card__listdate') or card.find('time', class_='job-search-card__listdate--new')
        posted_date = date_elem.get('datetime', '') if date_elem else ""
        
        if not job_url or not title:
            continue
            
        existing = Opening.query.filter_by(company_id=company.id, title=title).first()
        if existing:
            existing.last_seen_at = now
            existing.status = "open"
            if posted_date:
                existing.first_seen_at = posted_date
            jobs_updated += 1
        else:
            o = Opening(
                company_id=company.id,
                title=title,
                location=location,
                url=job_url,
                source="linkedin_deep_scan",
                first_seen_at=posted_date if posted_date else now,
                last_seen_at=now,
            )
            db.session.add(o)
            jobs_added += 1
            
    db.session.commit()
    company.touch()
    
    return jsonify({
        "success": True,
        "added": jobs_added,
        "updated": jobs_updated,
        "total": jobs_added + jobs_updated
    })
