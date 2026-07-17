"""
wellfound_scraper.py — Scrapes Wellfound (AngelList Talent) using Playwright with stealth.
Uses their /jobs search endpoint which works without auth.
"""
import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = { runtime: {} };
"""

def scrape_wellfound(keyword: str, location: str) -> list:
    """Scrape Wellfound for startup jobs."""
    jobs = []
    # Wellfound search works better with simple role terms
    simple_kw = keyword.split()[0] if keyword else "software"
    loc_slug = location.split(",")[0].strip().lower().replace(" ", "-")
    
    url = f"https://wellfound.com/jobs?q={urllib.parse.quote(simple_kw)}&l={urllib.parse.quote(loc_slug)}"

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(
                headless=True,
                firefox_user_prefs={
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False,
                }
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Kolkata",
            )
            context.add_init_script(STEALTH_SCRIPT)
            page = context.new_page()
            
            # Block images/fonts to speed up
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())
            
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                page.wait_for_selector("[class*='JobListing'], [class*='job-listing'], [data-testid*='job']", timeout=8000)
            except:
                pass
            page.evaluate("window.scrollBy(0, 500)")
            page.wait_for_timeout(1500)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        
        # Wellfound uses Tailwind + React. Look for job listing divs
        cards = soup.find_all("div", class_=lambda c: c and ("styles_component" in c or "JobSearchResult" in c or "listing" in c.lower()) if c else False)
        if not cards:
            # Broader fallback: any link with /jobs/ in href
            cards = [a.find_parent("div") for a in soup.find_all("a", href=lambda h: h and "/jobs/" in h)]
            cards = [c for c in cards if c][:20]

        seen_urls = set()
        for card in cards:
            title_el = card.find(["h2", "h3", "h4"]) or card.find("a")
            link_el = card.find("a", href=lambda h: h and "/jobs/" in h)
            company_el = card.find(class_=lambda c: c and "company" in c.lower() if c else False)
            if title_el and link_el:
                href = link_el["href"]
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                if href.startswith("/"):
                    href = "https://wellfound.com" + href
                jobs.append({
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "Wellfound Startup",
                    "location": location,
                    "url": href,
                    "posted_date": "Recently",
                    "source": "Wellfound",
                    "company_type": "Startup"
                })
    except Exception as e:
        log.error(f"Wellfound scrape failed: {e}")

    return jobs
