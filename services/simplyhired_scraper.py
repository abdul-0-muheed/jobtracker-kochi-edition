import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

def scrape_simplyhired(role: str, location: str) -> list:
    """Scrape SimplyHired using Playwright."""
    jobs = []
    query = urllib.parse.quote(role)
    loc = urllib.parse.quote(location)
    
    url = f"https://www.simplyhired.co.in/search?q={query}&l={loc}"
    
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
                page.wait_for_selector("#job-list", timeout=5000)
            except:
                pass
            
            html = page.content()
            browser.close()
            
            soup = BeautifulSoup(html, 'lxml')
            for card in soup.find_all('li', class_='css-0'):
                title_elem = card.find('a', class_='chakra-button')
                company_elem = card.find('span', class_='css-1rvxsbc') or card.find('span', {'data-testid': 'companyName'})
                loc_elem = card.find('span', class_='css-1tdefah') or card.find('span', {'data-testid': 'searchSerpJobLocation'})
                
                if title_elem and company_elem:
                    href = title_elem.get('href', '')
                    if href.startswith('/'):
                        href = "https://www.simplyhired.co.in" + href
                    jobs.append({
                        "title": title_elem.get_text(strip=True),
                        "company": company_elem.get_text(strip=True),
                        "location": loc_elem.get_text(strip=True) if loc_elem else location,
                        "url": href,
                        "posted_date": "",
                        "source": "SimplyHired"
                    })
    except Exception as e:
        log.error(f"SimplyHired scrape failed: {e}")
        
    return jobs
