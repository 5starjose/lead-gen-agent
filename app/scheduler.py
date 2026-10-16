"""APScheduler daily jobs — in-process scheduler for the single deployable service.
On Render/Fly/Railway the same service stays up; the scheduler persists via the DB
(ResearchRun run_key idempotency prevents duplicate scheduled runs after restarts)."""
import datetime, os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from .db import SessionLocal
from .models import Campaign
from .runner import run_campaign

scheduler = BackgroundScheduler()

def scheduler_disabled():
    """Scheduler must never run under tests: its background thread and
    sync_jobs() sessions race test fixtures that reset the database.
    Disabled when APP_ENV=test or DISABLE_SCHEDULER=1."""
    return os.getenv("APP_ENV") == "test" or os.getenv("DISABLE_SCHEDULER") == "1"

def _run(campaign_id):
    db = SessionLocal()
    try:
        c = db.get(Campaign, campaign_id)
        if c and c.active and not c.paused:
            run_campaign(db, c, trigger="scheduled")
    finally:
        db.close()

def sync_jobs():
    if scheduler_disabled():
        return
    for job in list(scheduler.get_jobs()):
        if job.id.startswith("campaign-"):
            scheduler.remove_job(job.id)
    db = SessionLocal()
    try:
        for c in db.query(Campaign).filter_by(active=True, paused=False).all():
            try: hh, mm = (c.schedule_time or "06:00").split(":")
            except Exception: hh, mm = "06", "00"
            scheduler.add_job(_run, CronTrigger(hour=int(hh), minute=int(mm), timezone=c.timezone or "America/Los_Angeles"),
                              args=[c.id], id=f"campaign-{c.id}", replace_existing=True, misfire_grace_time=3600)
    finally:
        db.close()

def start_scheduler():
    if scheduler_disabled():
        return
    if not scheduler.running:
        scheduler.start()
    sync_jobs()

def next_run_time():
    jobs = [j.next_run_time for j in scheduler.get_jobs() if j.next_run_time]
    return min(jobs).isoformat() if jobs else None
