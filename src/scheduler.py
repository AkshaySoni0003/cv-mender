import streamlit as st


def _run_scrape() -> None:
    """
    Called by APScheduler every 24 h.
    Reads config from DB, scrapes LinkedIn, inserts new jobs.
    Silently exits if the app is not yet configured.
    """
    # Local imports so this module loads fast on import
    from src.database import get_config, insert_jobs, touch_last_scraped, init_db
    from src.scraper import scrape_jobs

    init_db()  # idempotent — ensures tables exist even on scheduler wakeup

    config = get_config()
    if not config or not config.get("keywords"):
        return

    try:
        jobs = scrape_jobs(
            config["keywords"],
            config["location"],
            max_jobs=config.get("max_jobs", 25),
        )
        if jobs:
            n = insert_jobs(jobs)
            touch_last_scraped()
            print(f"[Scheduler] Daily scrape complete — {n} new job(s) added.")
        else:
            print("[Scheduler] Daily scrape returned no jobs.")
    except Exception as exc:
        # Log but never crash the scheduler thread
        print(f"[Scheduler] Daily scrape failed: {exc}")


@st.cache_resource
def start_scheduler():
    """
    Create and start a singleton BackgroundScheduler shared across all
    Streamlit sessions (guaranteed by st.cache_resource).
    Safe to call on every page load — the resource is only created once.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_scrape,
        trigger="interval",
        hours=24,
        id="daily_scrape",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started — daily LinkedIn scrape scheduled every 24 h.")
    return scheduler
