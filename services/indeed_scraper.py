import logging
from playwright.sync_api import sync_playwright
import urllib.parse
from bs4 import BeautifulSoup
import time

log = logging.getLogger(__name__)

def scrape_indeed(keyword: str, location: str) -> list:
    """Scrape Indeed using Playwright. (High chance of Cloudflare block, but we try)."""
    jobs = []
    query = urllib.parse.quote(keyword)
    loc = urllib.parse.quote(location)
    
    url = f"https://in.indeed.com/jobs?q={query}&l={loc}"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            
            # Hide webdriver flag
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Random sleep to mimic human
            time.sleep(2)
            
            html = page.content()
            browser.close()
            
            soup = BeautifulSoup(html, 'lxml')
            
            # Indeed job cards usually have class 'result' or 'job_seen_beacon'
            for card in soup.find_all('div', class_=lambda c: c and ('job_seen_beacon' in c or 'result' in c)):
                title_elem = card.find('h2', class_='jobTitle') or card.find('a', class_='jcs-JobTitle')
                company_elem = card.find('span', class_='companyName') or card.find('span', attrs={'data-testid': 'company-name'})
                loc_elem = card.find('div', class_='companyLocation') or card.find('div', attrs={'data-testid': 'text-location'})
                
                link_elem = card.find('a', class_='jcs-JobTitle') or (title_elem.find('a') if title_elem else None)
                
                date_elem = card.find('span', class_='date')
                
                if title_elem and company_elem and link_elem:
                    href = link_elem.get('href', '')
                    if href.startswith('/'):
                        href = "https://in.indeed.com" + href
                        
                    jobs.append({
                        "title": title_elem.get_text(strip=True),
                        "company": company_elem.get_text(strip=True),
                        "location": loc_elem.get_text(strip=True) if loc_elem else location,
                        "url": href,
                        "posted_date": date_elem.get_text(strip=True) if date_elem else "",
                        "source": "Indeed"
                    })
    except Exception as e:
        log.error(f"Indeed scrape failed: {e}")
        
    return jobs
