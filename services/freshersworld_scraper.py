"""
freshersworld_scraper.py — Scrapes Freshersworld using Playwright.
"""
import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def scrape_freshersworld(role: str, location: str) -> list:
    """Scrape Freshersworld for fresher and intern jobs."""
    jobs = []
    # Freshersworld URL format
    role_slug = role.replace(" ", "-")
    loc_slug = location.split(",")[0].strip().replace(" ", "-").lower()
    url = f"https://www.freshersworld.com/jobs/jobsearch/{urllib.parse.quote(role)}-jobs-for-fresher-in-{loc_slug}-0"

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                page.wait_for_selector(".job-container, .job-listing-card, [class*='job']", timeout=7000)
            except:
                pass

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        for card in soup.find_all("div", class_=lambda c: c and ("job-container" in c or "job-listing" in c) if c else False):
            title_el = card.find(["h2", "h3", "a"])
            company_el = card.find(class_=lambda c: c and "company" in c.lower() if c else False)
            link_el = card.find("a", href=True)
            date_el = card.find(class_=lambda c: c and "date" in c.lower() if c else False)
            if title_el:
                href = link_el["href"] if link_el else ""
                if href.startswith("/"):
                    href = "https://www.freshersworld.com" + href
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "Company",
                    "location": location,
                    "url": href,
                    "posted_date": date_el.get_text(strip=True) if date_el else "",
                    "source": "Freshersworld"
                })
    except Exception as e:
        log.error(f"Freshersworld scrape failed: {e}")

    return jobs
