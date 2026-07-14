"""debug_scraper.py — Test career scraper and LinkedIn scraper with real data."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from services.career_scraper import scrape_career_page
import sqlite3
from pathlib import Path

DB = Path.home() / '.jobtracker' / 'data.db'
con = sqlite3.connect(str(DB))
cur = con.cursor()

# Get companies that have career pages
cur.execute("""
    SELECT id, name, career_page_url, website
    FROM companies
    WHERE career_page_url IS NOT NULL AND career_page_url != ''
    LIMIT 10
""")
companies = cur.fetchall()
con.close()

print(f"Testing {len(companies)} companies with career pages\n")
print("="*60)

total_found = 0
for cid, name, career_url, website in companies[:5]:
    print(f"\n[{cid}] {name}")
    print(f"  Career URL: {career_url}")
    try:
        jobs = scrape_career_page(career_url, delay=(0.5, 1))
        print(f"  Jobs found: {len(jobs)}")
        for j in jobs[:3]:
            print(f"    • {j.get('title', '?')[:60]} | {j.get('location','')[:30]}")
        total_found += len(jobs)
    except Exception as e:
        print(f"  ERROR: {e}")

print(f"\n{'='*60}")
print(f"Total jobs found across {min(5, len(companies))} companies: {total_found}")

# Also check what's in DB already
con = sqlite3.connect(str(DB))
cur = con.cursor()
cur.execute("SELECT COUNT(*) FROM openings WHERE status='open'")
print(f"Existing open openings in DB: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM scraping_jobs")
print(f"Total scraping jobs run: {cur.fetchone()[0]}")
cur.execute("SELECT status, COUNT(*) FROM scraping_jobs GROUP BY status")
print("Scraping job statuses:", dict(cur.fetchall()))
con.close()
