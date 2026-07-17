import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

def scrape_foundit(keyword: str, location: str) -> list:
    """Scrape Foundit (Monster) using Playwright."""
    jobs = []
    query = urllib.parse.quote(keyword)
    loc = urllib.parse.quote(location)
    
    url = f"https://www.foundit.in/srp/results?query={query}&locations={loc}"
    
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
                page.wait_for_selector(".srpResultCard", timeout=5000)
            except:
                pass
            
            html = page.content()
            browser.close()
            
            soup = BeautifulSoup(html, 'lxml')
            for card in soup.find_all(class_='srpResultCard'):
                title_elem = card.find(class_='jobTitle')
                company_elem = card.find(class_='companyName')
                loc_elem = card.find(class_='details')
                link_elem = title_elem.find_parent('a') if title_elem else None
                
                if title_elem and company_elem:
                    link_el = card.find("a", href=True)
                    href = link_el["href"] if link_el else ""
                    if href.startswith("/"):
                        href = "https://www.foundit.in" + href
                    date_elem = card.find(class_=lambda c: c and "date" in c.lower() if c else False)
                    jobs.append({
                        "title": title_elem.get_text(strip=True),
                        "company": company_elem.get_text(strip=True),
                        "location": loc_elem.get_text(strip=True) if loc_elem else location,
                        "url": href,
                        "posted_date": date_elem.get_text(strip=True) if date_elem else "",
                        "source": "Foundit"
                    })
    except Exception as e:
        log.error(f"Foundit scrape failed: {e}")
        
    return jobs
