"""
deep_scraper.py — Time-gapped background queue that scrapes 14+ job platforms
PLUS all companies in the user's watchlist (career page scraping).

Phase 1: Job portals (LinkedIn, Naukri, Indeed, etc.) with 3-10s evasion delays
Phase 2: Company career pages from the user's Companies list
Results stored in ScrapedJob table (NOT Company/Opening CRM).
"""
import logging
import time
import random
import uuid
import threading
from typing import Dict, List, Any
from models import db, ScrapedJob, _now_iso
from services.playwright_scrapers import score_job

log = logging.getLogger(__name__)

# In-memory job status store (keyed by job_id)
DEEP_SCRAPE_STATUS: Dict[str, Dict[str, Any]] = {}


def start_deep_scrape(queries: List[str], location: str, intern_only: bool, app_obj) -> str:
    """Initialize and start a deep scrape in a background thread."""
    job_id = str(uuid.uuid4())

    limited_queries = queries[:2]  # max 2 role queries

    DEEP_SCRAPE_STATUS[job_id] = {
        "status": "running",
        "completed_scrapers": 0,
        "total_scrapers": len(limited_queries) * 14,  # updated live when companies are counted
        "total_jobs_found": 0,
        "phase": "Phase 1: Job Portals",
        "logs": [f"🚀 Deep Scrape started! Scanning {len(limited_queries) * 14} platform calls + your Companies list..."]
    }

    thread = threading.Thread(
        target=_run_deep_scrape,
        args=[job_id, limited_queries, location, intern_only, app_obj],
        daemon=True
    )
    thread.start()

    return job_id


def _save_job(job: dict, source_override: str = None) -> bool:
    """Save a job dict to ScrapedJob. Returns True if newly inserted."""
    from services.playwright_scrapers import score_job as _score
    url = (job.get("url") or "").strip()
    title = (job.get("title") or "").strip()
    if not url or not title:
        return False

    score = _score(job)
    if score <= 0:
        return False

    try:
        exists = ScrapedJob.query.filter_by(url=url).first()
        if not exists:
            sj = ScrapedJob(
                title=title,
                company=job.get("company", "Unknown") or "Unknown",
                location=job.get("location", "") or "",
                url=url,
                source=source_override or job.get("source", ""),
                company_type=job.get("company_type", "IT / Tech") or "IT / Tech",
                posted_date=job.get("posted_date", "") or "",
                ats_score=score,
                scraped_at=_now_iso()
            )
            db.session.add(sj)
            return True
    except Exception as e:
        log.error(f"_save_job error: {e}")
    return False


def _run_deep_scrape(job_id: str, queries: List[str], location: str, intern_only: bool, app_obj):
    """Background task: Phase 1 = job portals, Phase 2 = company career pages."""
    with app_obj.app_context():
        from services.playwright_scrapers import scrape_linkedin_global, scrape_naukri
        from services.internshala_scraper import scrape_internshala
        from services.foundit_scraper import scrape_foundit
        from services.indeed_scraper import scrape_indeed
        from services.wellfound_scraper import scrape_wellfound
        from services.glassdoor_scraper import scrape_glassdoor
        from services.simplyhired_scraper import scrape_simplyhired
        from services.shine_scraper import scrape_shine
        from services.remoteok_scraper import scrape_remoteok
        from services.technopark_scraper import scrape_technopark
        from services.freshersworld_scraper import scrape_freshersworld
        from services.cutshort_scraper import scrape_cutshort
        from services.hirist_scraper import scrape_hirist
        from services.instahyre_scraper import scrape_instahyre
        from services.career_scraper import scrape_career_page
        from models import Company

        # Platform registry: (function, name, needs_intern_flag)
        SCRAPERS = [
            (scrape_linkedin_global, "LinkedIn", True),
            (scrape_naukri, "Naukri", True),
            (scrape_internshala, "Internshala", False),
            (scrape_foundit, "Foundit", False),
            (scrape_indeed, "Indeed", False),
            (scrape_wellfound, "Wellfound", False),
            (scrape_glassdoor, "Glassdoor", False),
            (scrape_simplyhired, "SimplyHired", False),
            (scrape_shine, "Shine", False),
            (scrape_remoteok, "RemoteOK", False),
            (scrape_technopark, "Technopark", False),
            (scrape_freshersworld, "Freshersworld", False),
            (scrape_cutshort, "Cutshort", False),
            (scrape_instahyre, "Instahyre", False),
        ]

        status = DEEP_SCRAPE_STATUS.get(job_id)
        if not status:
            return

        jobs_saved = 0

        try:
            # ── PHASE 1: Job Portal Scrapers ──────────────────────────────────
            status["phase"] = "Phase 1: Job Portals"
            status["logs"].append("═══ PHASE 1: Scraping job portals... ═══")

            for query in queries:
                for func, name, uses_intern_flag in SCRAPERS:
                    sleep_time = random.uniform(3, 10)
                    status["logs"].append(f"⏳ {sleep_time:.1f}s gap → {name}...")
                    time.sleep(sleep_time)

                    try:
                        if uses_intern_flag:
                            result = func(query, location, intern_only)
                        else:
                            result = func(query, location)

                        found = len(result) if result else 0
                        status["total_jobs_found"] += found
                        if found > 0:
                            status["logs"].append(f"[SUCCESS] ✅ {name} → {found} jobs")
                            for job in result:
                                if _save_job(job):
                                    jobs_saved += 1
                        else:
                            status["logs"].append(f"[WARNING] ⚠️ {name} → 0 jobs")

                    except Exception as e:
                        log.error(f"Deep Scrape: {name} failed: {e}")
                        status["logs"].append(f"[FAILED] ❌ {name} → {str(e)[:80]}")

                    status["completed_scrapers"] += 1

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

            # ── PHASE 2: Company Career Pages ─────────────────────────────────
            status["phase"] = "Phase 2: Your Companies"
            status["logs"].append("═══ PHASE 2: Scraping your Companies career pages... ═══")

            companies = Company.query.filter(
                Company.career_page_url.isnot(None),
                Company.career_page_url != ""
            ).order_by(Company.match_score.desc()).all()

            status["logs"].append(f"📋 Found {len(companies)} companies with career pages")
            status["total_scrapers"] += len(companies)

            for company in companies:
                status["logs"].append(f"🔍 Scraping {company.name} career page...")

                try:
                    jobs = scrape_career_page(company.career_page_url, delay=(0, 1))
                    found = len(jobs) if jobs else 0
                    status["total_jobs_found"] += found

                    newly_saved = 0
                    for job in jobs:
                        job["company"] = company.name
                        job["company_type"] = company.company_type or "IT / Tech"
                        job["source"] = f"{company.name} (Career Page)"
                        if _save_job(job, source_override=f"{company.name} (Career Page)"):
                            newly_saved += 1
                            jobs_saved += 1

                    if found > 0:
                        status["logs"].append(f"[SUCCESS] ✅ {company.name} → {found} jobs ({newly_saved} new saved)")
                    else:
                        status["logs"].append(f"[WARNING] ⚠️ {company.name} → 0 jobs")

                except Exception as e:
                    log.error(f"Career page scrape failed for {company.name}: {e}")
                    status["logs"].append(f"[FAILED] ❌ {company.name} → {str(e)[:80]}")

                status["completed_scrapers"] += 1

                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            # ── DONE ───────────────────────────────────────────────────────────
            status["logs"].append(
                f"[SUCCESS] 🎉 COMPLETE! "
                f"Scraped {status['total_jobs_found']} total | "
                f"Saved {jobs_saved} new ATS-matched jobs"
            )
            status["status"] = "done"
            log.info(
                f"[DEEP SCRAPE COMPLETE] job_id={job_id} "
                f"total_scraped={status['total_jobs_found']} saved={jobs_saved}"
            )

        except Exception as e:
            log.error(f"Deep Scrape CRITICAL: {e}")
            status["status"] = "error"
            status["logs"].append(f"[FAILED] CRITICAL ERROR: {e}")
