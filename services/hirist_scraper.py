"""
hirist_scraper.py — Scrapes Hirist.tech for software engineer jobs in India.
"""
import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def scrape_hirist(role: str, location: str) -> list:
    """Scrape Hirist.tech for software jobs."""
    jobs = []
    query = urllib.parse.quote(role)
    loc = urllib.parse.quote(location.split(",")[0].strip())
    url = f"https://www.hirist.tech/j/search?q={query}&l={loc}&exp=0-2"

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
                page.wait_for_selector("[class*='jobCard'], [class*='job-card'], .job-listing", timeout=8000)
            except:
                pass

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        # Try multiple card selectors
        cards = (
            soup.find_all(class_=lambda c: c and "jobCard" in c if c else False) or
            soup.find_all(class_=lambda c: c and "job-card" in c if c else False) or
            soup.find_all("article") or
            []
        )
        for card in cards:
            title_el = card.find(["h2", "h3", "h4", "a"])
            company_el = card.find(class_=lambda c: c and ("company" in c.lower() or "employer" in c.lower()) if c else False)
            link_el = card.find("a", href=True)
            if title_el and link_el:
                href = link_el["href"]
                if href.startswith("/"):
                    href = "https://www.hirist.tech" + href
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "Tech Company",
                    "location": location,
                    "url": href,
                    "posted_date": "",
                    "source": "Hirist"
                })
    except Exception as e:
        log.error(f"Hirist scrape failed: {e}")

    return jobs
