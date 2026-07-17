from __future__ import annotations

import logging
from flask import Blueprint, jsonify, render_template, request
from models import UserSetting, db
from services.playwright_scrapers import scrape_linkedin_global, scrape_naukri, score_job

log = logging.getLogger(__name__)

aggregator_bp = Blueprint("aggregator", __name__, url_prefix="/aggregator")

# The skills from the user's CV
DEFAULT_CV_SKILLS = ["React", "Next.js", "Python", "FastAPI", "Frontend", "Full-stack", "JavaScript"]

@aggregator_bp.route("/")
def search_jobs_page():
    """Main global search page."""
    # Get user settings
    role = UserSetting.query.filter_by(key="search_role").first()
    loc = UserSetting.query.filter_by(key="search_loc").first()
    exp = UserSetting.query.filter_by(key="search_exp").first()
    
    settings = {
        "role": role.value if role else "Frontend Developer",
        "location": loc.value if loc else "Kochi",
        "experience": exp.value if exp else "Internship"
    }
    return render_template("search.html", settings=settings)

@aggregator_bp.route("/api/search", methods=["POST"])
def api_search():
    from services.playwright_scrapers import load_cv_config
    cv_config = load_cv_config()
    search_queries = cv_config.get("search_queries", ["Software Developer Intern Kochi"])
    
    # Take the top 3 search queries to avoid extreme timeout
    queries_to_run = search_queries[:3]
    
    # We no longer ask the user for a role. We search broadly using ATS config
    data = request.get_json(force=True, silent=True) or {}
    
    location = data.get("location", "Kochi")
    experience = data.get("experience", "Internship")
    
    # Save settings
    for k, v in [("search_loc", location), ("search_exp", experience)]:
        setting = UserSetting.query.filter_by(key=k).first()
        if setting:
            setting.value = v
        else:
            db.session.add(UserSetting(key=k, value=v))
    db.session.commit()
    
    intern_only = (experience.lower() == "internship")
    
    def generate():
        yield json.dumps({"status": "started", "message": "Initializing 7 scrapers..."}) + "\n"
        
        all_jobs = []
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from services.playwright_scrapers import scrape_linkedin_global, scrape_naukri, score_job
        from services.internshala_scraper import scrape_internshala
        from services.foundit_scraper import scrape_foundit
        from services.indeed_scraper import scrape_indeed
        from services.wellfound_scraper import scrape_wellfound
        from services.glassdoor_scraper import scrape_glassdoor

        # ThreadPool to run scrapers concurrently
        with ThreadPoolExecutor(max_workers=7) as executor:
            future_to_name = {}
            for query in queries_to_run:
                search_loc = location
                if "kochi" in search_loc.lower():
                    search_loc = "Kochi, Ernakulam"
                    
                future_to_name[executor.submit(scrape_linkedin_global, query, search_loc, intern_only)] = "LinkedIn"
                future_to_name[executor.submit(scrape_naukri, query, search_loc, intern_only)] = "Naukri"
                future_to_name[executor.submit(scrape_internshala, query, search_loc)] = "Internshala"
                future_to_name[executor.submit(scrape_foundit, query, search_loc)] = "Foundit"
                future_to_name[executor.submit(scrape_indeed, query, search_loc)] = "Indeed"
                future_to_name[executor.submit(scrape_wellfound, query, search_loc)] = "Wellfound"
                future_to_name[executor.submit(scrape_glassdoor, query, search_loc)] = "Glassdoor"
                
            total = len(future_to_name)
            completed = 0
            
            for future in as_completed(future_to_name):
                scraper_name = future_to_name[future]
                completed += 1
                try:
                    result = future.result()
                    if result:
                        all_jobs.extend(result)
                    
                    found_count = len(result) if result else 0
                    print(f"[{completed}/{total}] [SUCCESS] {scraper_name} returned {found_count} raw jobs.", flush=True)
                    yield json.dumps({"status": "progress", "scraper": scraper_name, "found": found_count, "completed": completed, "total": total}) + "\n"
                except Exception as e:
                    print(f"[{completed}/{total}] [FAILED] {scraper_name} error: {e}", flush=True)
                    yield json.dumps({"status": "progress", "scraper": scraper_name, "found": 0, "error": str(e), "completed": completed, "total": total}) + "\n"
            
        print(f"\n[COMPLETE] Scraped {len(all_jobs)} total raw jobs across all platforms.", flush=True)
            
        # Deduplicate jobs by URL
        unique_jobs = {job['url']: job for job in all_jobs if job.get('url')}
        all_jobs = list(unique_jobs.values())
        
        # Score and filter based on advanced ATS CV rules
        for job in all_jobs:
            job["cv_score"] = score_job(job)
            if "company_type" not in job:
                job["company_type"] = "IT / Tech"
            
        # STRICT FILTERS:
        filtered_jobs = []
        for job in all_jobs:
            loc_text = job.get("location", "").lower()
            is_kochi = ("kochi" in loc_text or "ernakulam" in loc_text or "cochin" in loc_text or "kerala" in loc_text)
            target_loc = location.lower()
            if "kochi" in target_loc and not is_kochi:
                continue
            if job["cv_score"] > 0:
                filtered_jobs.append(job)
            
        def date_rank(date_str):
            d = date_str.lower()
            if not d or "recent" in d or "today" in d or "just" in d or "hour" in d or "min" in d:
                return 0
            if "1 day" in d or "24" in d: return 1
            if "2 day" in d: return 2
            if "3 day" in d: return 3
            if "4 day" in d: return 4
            if "5 day" in d: return 5
            if "6 day" in d: return 6
            if "week" in d and "1" in d: return 7
            if "week" in d and "2" in d: return 14
            if "month" in d: return 30
            return 99 # unknown or older
            
        filtered_jobs.sort(key=lambda x: (-x["cv_score"], date_rank(x.get("posted_date", ""))))
        
        yield json.dumps({"status": "done", "total": len(filtered_jobs), "jobs": filtered_jobs}) + "\n"

    from flask import Response
    import json
    if not queries_to_run:
        return jsonify({"error": "No valid queries found."}), 400
        
    return Response(generate(), mimetype='application/json-lines')

@aggregator_bp.route('/api/deep-scrape', methods=['POST'])
def start_deep_scrape_endpoint():
    """Trigger the background Deep Scrape job."""
    from services.playwright_scrapers import load_cv_config
    data = request.json or {}
    location = data.get('location', 'Kochi')
    experience = data.get('experience', 'Internship')
    
    intern_only = (experience.lower() == "internship")
    
    # Save settings
    for k, v in data.items():
        existing = UserSetting.query.filter_by(key=k).first()
        if existing:
            existing.value = v
        else:
            db.session.add(UserSetting(key=k, value=v))
    db.session.commit()
    
    # Build queries
    config = load_cv_config()
    target = config.get("target_profile", {})
    exp_level = target.get("experience", "Fresher / Recent Graduate")
    roles = []
    for cat in config.get("job_roles", []):
        roles.extend(cat.get("roles", []))
    
    queries_to_run = roles[:3] if roles else ["Software Engineer Intern", "Software Developer Intern"]
    
    from services.deep_scraper import start_deep_scrape
    from flask import current_app
    app_obj = current_app._get_current_object()
    job_id = start_deep_scrape(queries_to_run, location, intern_only, app_obj)
    
    return jsonify({"job_id": job_id, "status": "started"})

@aggregator_bp.route('/api/deep-scrape/status/<job_id>', methods=['GET'])
def deep_scrape_status(job_id):
    """Check the status of a Deep Scrape job."""
    from services.deep_scraper import DEEP_SCRAPE_STATUS
    status = DEEP_SCRAPE_STATUS.get(job_id)
    if not status:
        return jsonify({"error": "Job not found"}), 404
        
    return jsonify(status)
