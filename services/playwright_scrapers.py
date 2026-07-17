import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup
import time
import httpx

log = logging.getLogger(__name__)

def scrape_linkedin_global(role: str, location: str, intern_only: bool) -> list:
    """Scrape LinkedIn Guest API."""
    jobs = []
    # f_E=1 is Internship, 2 is Entry Level
    experience = "1" if intern_only else "1%2C2"
    query = urllib.parse.quote(role)
    loc = urllib.parse.quote(location)
    
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query}&location={loc}&f_E={experience}&start=0"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'lxml')
        for card in soup.find_all('li'):
            title_elem = card.find('h3', class_='base-search-card__title')
            company_elem = card.find('h4', class_='base-search-card__subtitle')
            loc_elem = card.find('span', class_='job-search-card__location')
            link_elem = card.find('a', class_='base-card__full-link')
            date_elem = card.find('time', class_='job-search-card__listdate') or card.find('time', class_='job-search-card__listdate--new')
            
            if title_elem and link_elem and company_elem:
                jobs.append({
                    "title": title_elem.get_text(strip=True),
                    "company": company_elem.get_text(strip=True),
                    "location": loc_elem.get_text(strip=True) if loc_elem else location,
                    "url": link_elem.get('href', '').split('?')[0],
                    "posted_date": date_elem.get('datetime', '') if date_elem else "",
                    "source": "LinkedIn"
                })
    except Exception as e:
        log.error(f"LinkedIn global scrape failed: {e}")
        
    return jobs

def scrape_naukri(role: str, location: str, intern_only: bool) -> list:
    """Scrape Naukri using Playwright."""
    jobs = []
    query = urllib.parse.quote(role)
    loc = urllib.parse.quote(location)
    
    # URL construction (simple keyword search)
    search_query = f"{query} internship" if intern_only else query
    url = f"https://www.naukri.com/{search_query}-jobs-in-{loc}"
    
    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Wait for job listings to load
            try:
                page.wait_for_selector(".srp-jobtuple-wrapper", timeout=5000)
            except:
                pass # Timeout if no jobs or blocked
            
            html = page.content()
            browser.close()
            
            soup = BeautifulSoup(html, 'lxml')
            for card in soup.find_all(class_='srp-jobtuple-wrapper'):
                title_elem = card.find('a', class_='title')
                company_elem = card.find('a', class_='comp-name')
                loc_elem = card.find('span', class_='locWdth')
                date_elem = card.find('span', class_='job-post-day')
                
                if title_elem and company_elem:
                    jobs.append({
                        "title": title_elem.get_text(strip=True),
                        "company": company_elem.get_text(strip=True),
                        "location": loc_elem.get_text(strip=True) if loc_elem else location,
                        "url": title_elem.get('href', ''),
                        "posted_date": date_elem.get_text(strip=True) if date_elem else "",
                        "source": "Naukri"
                    })
    except Exception as e:
        log.error(f"Naukri scrape failed: {e}")
        
    return jobs

import json
import os

def load_cv_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cv_config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except:
        return {}

def score_job(job: dict) -> int:
    """Score a job based on the advanced ATS cv_config.json."""
    config = load_cv_config()
    if not config:
        return 1 # fallback

    score = 0
    title = job.get('title', '').lower()
    company = job.get('company', '').lower()
    text = f"{title} {company}"
    
    # 1. Avoid Roles (Instant -100 score to filter out)
    avoid_roles = config.get("avoid_roles", [])
    for avoid in avoid_roles:
        if avoid.lower() in text:
            return -100
            
    # 2. Generic tech check for base points (from job_roles categories)
    generic_passed = False
    for category in config.get("job_roles", []):
        for role in category.get("roles", []):
            if role.lower() in text:
                score += 5
                generic_passed = True
                
    if not generic_passed and ("software" in text or "developer" in text or "intern" in text or "engineer" in text):
        score += 2
        
    # 3. Primary Skills matching
    primary_skills = config.get("target_profile", {}).get("primary_skills", [])
    for skill in primary_skills:
        if skill.lower() in text:
            score += 15
            
    # 4. ATS Keywords matching
    ats = config.get("ats_keywords", {})
    for category, keywords in ats.items():
        for kw in keywords:
            if kw.lower() in text:
                score += 10
                
    return score
