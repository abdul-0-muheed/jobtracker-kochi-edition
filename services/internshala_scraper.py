import logging
import httpx
from bs4 import BeautifulSoup
import urllib.parse

log = logging.getLogger(__name__)

def scrape_internshala(keyword: str, location: str) -> list:
    """Scrape Internshala for freshers and internships."""
    jobs = []
    
    # Internshala is very strict with long hyphenated keywords and will return 0 jobs.
    # We take just the first primary keyword (e.g., 'Software' or 'React')
    primary_kw = keyword.split()[0].lower() if keyword else "software"
    
    # Remove location from kw if it was passed by mistake
    loc = "kochi" if "kochi" in location.lower() else location.replace(" ", "-").lower()
    
    url = f"https://internshala.com/internships/keywords-{primary_kw}-internships-in-{loc}/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    try:
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'lxml')
        
        for card in soup.find_all('div', class_=lambda c: c and 'individual_internship' in c):
            title_elem = card.find('h2', class_='job-internship-name') or card.find('h3', class_='job-internship-name')
            company_elem = card.find('p', class_='company-name') or card.find('a', class_='link_display_like_text')
            loc_elem = card.find('a', class_='location_link')
            link_elem = title_elem.find('a') if title_elem else None
            
            # They use a specific div for status/date
            date_elem = card.find('div', class_='status-inactive') or card.find('div', class_='status')
            date_text = date_elem.get_text(strip=True) if date_elem else "Recently"
            
            if title_elem and company_elem and link_elem:
                href = link_elem.get('href', '')
                if href.startswith('/'):
                    href = "https://internshala.com" + href
                    
                jobs.append({
                    "title": title_elem.get_text(strip=True),
                    "company": company_elem.get_text(strip=True),
                    "location": loc_elem.get_text(strip=True) if loc_elem else location,
                    "url": href,
                    "posted_date": date_text,
                    "source": "Internshala",
                    "company_type": "Startup/SME"
                })
    except Exception as e:
        log.error(f"Internshala scrape failed for {keyword}: {e}")
        
    return jobs
