from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .sync import sync_all

_scheduler: BackgroundScheduler | None = None


def start_scheduler(hour: int = 18, minute: int = 30) -> BackgroundScheduler:
    """Start one local scheduler; the job runs Saturday through Thursday."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Tehran")
        _scheduler.start()

    trigger = CronTrigger(
        day_of_week="sat,sun,mon,tue,wed,thu",
        hour=hour,
        minute=minute,
        timezone="Asia/Tehran",
    )
    job = _scheduler.get_job("daily-market-sync")
    if job:
        job.modify(trigger=trigger)
    else:
        _scheduler.add_job(
            sync_all,
            trigger=trigger,
            args=["AUTO"],
            id="daily-market-sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    return _scheduler


def update_schedule(hour: int, minute: int) -> None:
    if _scheduler is not None:
        job = _scheduler.get_job("daily-market-sync")
        if job:
            job.modify(
                trigger=CronTrigger(
                    day_of_week="sat,sun,mon,tue,wed,thu",
                    hour=hour,
                    minute=minute,
                    timezone="Asia/Tehran",
                )
            )


def next_run_time():
    if _scheduler is None:
        return None
    job = _scheduler.get_job("daily-market-sync")
    return job.next_run_time if job else None
