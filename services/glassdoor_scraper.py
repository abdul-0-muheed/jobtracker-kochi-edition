"""
glassdoor_scraper.py — Scrapes Glassdoor using their JSON API endpoint.
Glassdoor has an undocumented GraphQL/REST API that returns job listings as JSON.
This avoids the Cloudflare Turnstile challenge that blocks Playwright.
"""
import logging
import httpx
import urllib.parse

log = logging.getLogger(__name__)


def scrape_glassdoor(keyword: str, location: str) -> list:
    """Scrape Glassdoor via their internal API."""
    jobs = []
    
    # Glassdoor API endpoint (discovered via browser devtools)
    url = "https://www.glassdoor.co.in/api-web/employer/find.htm"
    
    params = {
        "autocomplete": "false",
        "locationStr": location.split(",")[0].strip(),
        "jobType": "",
        "q": keyword,
        "suggestCount": 0,
        "suggestChosen": False,
        "clickSource": "searchBtn",
        "sc.keyword": keyword,
        "locT": "C",
        "locId": "",
        "jobType": ""
    }
    
    # Try their job search API
    search_url = f"https://www.glassdoor.co.in/findPopularLocationAjax.htm"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.glassdoor.co.in/",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    try:
        # Use their GraphQL API endpoint for job search
        graphql_url = "https://www.glassdoor.co.in/graph"
        gql_payload = {
            "operationName": "JobSearchResultsQuery",
            "variables": {
                "keyword": keyword,
                "locationId": 0,
                "locationType": "CITY",
                "locationName": location.split(",")[0].strip(),
                "numJobsToShow": 20,
                "filterParams": [],
                "originalPageUrl": f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={urllib.parse.quote(keyword)}",
                "seoUrl": False
            },
            "query": """query JobSearchResultsQuery($keyword: String, $locationId: Int, $locationName: String, $numJobsToShow: Int) {
              jobListings(keyword: $keyword, locationId: $locationId, locationName: $locationName, numJobsToShow: $numJobsToShow) {
                jobViews { jobTitleText, employerName, locationName, jobListingId, listingDateText, jobLink }
              }
            }"""
        }
        
        resp = httpx.post(graphql_url, json=gql_payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            job_views = (
                data.get("data", {})
                .get("jobListings", {})
                .get("jobViews", [])
            )
            for j in job_views:
                link = j.get("jobLink", "")
                if link and not link.startswith("http"):
                    link = "https://www.glassdoor.co.in" + link
                jobs.append({
                    "title": j.get("jobTitleText", ""),
                    "company": j.get("employerName", "Glassdoor Company"),
                    "location": j.get("locationName", location),
                    "url": link,
                    "posted_date": j.get("listingDateText", ""),
                    "source": "Glassdoor",
                    "company_type": "Corporate/MNC"
                })
    except Exception as e:
        log.error(f"Glassdoor scrape failed: {e}")

    return jobs
