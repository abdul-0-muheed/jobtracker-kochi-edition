"""
technopark_scraper.py — Scrapes Technopark Thiruvananthapuram job listings.
Uses Playwright since the site is Inertia.js/Vue.
"""
import logging
from playwright.sync_api import sync_playwright
import json
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def scrape_technopark(role: str, location: str) -> list:
    """Scrape Technopark job listings using Playwright."""
    jobs = []
    keyword = role.split()[0] if role else "software"
    url = f"https://technopark.in/job-search?keyword={keyword}&type="

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            try:
                page.wait_for_selector(".job-card, .job-listing, [class*='job']", timeout=8000)
            except:
                pass

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")

        # Technopark is Inertia.js - job data may be in data-page attribute
        app_div = soup.find(id="app")
        if app_div and app_div.get("data-page"):
            page_data = json.loads(app_div["data-page"])
            props = page_data.get("props", {})
            listings = props.get("jobs") or props.get("listings") or props.get("results") or []
            if isinstance(listings, dict):
                listings = listings.get("data", [])
            for item in listings:
                title = item.get("title") or item.get("position") or item.get("job_title", "")
                company = item.get("company") or item.get("company_name", "")
                link = item.get("url") or item.get("link") or f"https://technopark.in/job-search"
                if title:
                    jobs.append({
                        "title": title,
                        "company": company or "Technopark Company",
                        "location": "Thiruvananthapuram, Kerala",
                        "url": link,
                        "posted_date": item.get("created_at", ""),
                        "source": "Technopark"
                    })

        # Fallback: parse HTML cards
        if not jobs:
            for card in soup.find_all("div", class_=lambda c: c and "job" in c.lower() if c else False):
                title_el = card.find(["h2", "h3", "a"])
                company_el = card.find(class_=lambda c: c and "company" in c.lower() if c else False)
                link_el = card.find("a", href=True)
                if title_el:
                    href = link_el["href"] if link_el else "https://technopark.in/job-search"
                    if href.startswith("/"):
                        href = "https://technopark.in" + href
                    jobs.append({
                        "title": title_el.get_text(strip=True),
                        "company": company_el.get_text(strip=True) if company_el else "Technopark Company",
                        "location": "Thiruvananthapuram, Kerala",
                        "url": href,
                        "posted_date": "",
                        "source": "Technopark"
                    })

    except Exception as e:
        log.error(f"Technopark scrape failed: {e}")

    return jobs
