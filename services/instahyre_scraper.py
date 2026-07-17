"""
instahyre_scraper.py — Scrapes Instahyre for tech jobs.
"""
import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def scrape_instahyre(role: str, location: str) -> list:
    """Scrape Instahyre for tech jobs."""
    jobs = []
    query = urllib.parse.quote(role)
    loc = urllib.parse.quote(location.split(",")[0].strip())
    url = f"https://www.instahyre.com/search-jobs/?q={query}&l={loc}"

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
                page.wait_for_selector(".job-card, .JobCard, [class*='jobCard'], [class*='job-item']", timeout=8000)
            except:
                pass
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        cards = (
            soup.find_all(class_=lambda c: c and "job" in c.lower() if c else False)
        )
        seen = set()
        for card in cards:
            title_el = card.find(["h2", "h3", "h4"])
            link_el = card.find("a", href=True)
            company_el = card.find(class_=lambda c: c and "company" in c.lower() if c else False)
            if title_el and link_el:
                href = link_el["href"]
                if href in seen:
                    continue
                seen.add(href)
                if href.startswith("/"):
                    href = "https://www.instahyre.com" + href
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "Tech Company",
                    "location": location,
                    "url": href,
                    "posted_date": "",
                    "source": "Instahyre"
                })
    except Exception as e:
        log.error(f"Instahyre scrape failed: {e}")

    return jobs
