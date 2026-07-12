"""Scheduling (Story 0.7, FR-19).

Parses config cadences and registers one job per enabled source. Uses APScheduler
when available (lazy import); otherwise exposes the parsed schedule so a caller
(or a cron/systemd timer) can drive it. A failing job isolates to itself (AD-12).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..core.config import SourceConfig, load_config
from .alerting import AlertLevel, get_alerter
from .logging import get_logger


@dataclass
class ScheduledJob:
    source_name: str
    cadence: str
    interval_seconds: Optional[int]  # None for time-of-day cadences


def _parse_cadence(cadence: str) -> Optional[int]:
    """Return an interval in seconds for simple cadences; None for daily@HH:MM."""
    c = cadence.strip().lower()
    if c.startswith("daily"):
        return None  # time-of-day; APScheduler cron handles it in production
    units = {"m": 60, "h": 3600, "d": 86400}
    if c and c[-1] in units and c[:-1].isdigit():
        return int(c[:-1]) * units[c[-1]]
    return None


class Scheduler:
    def __init__(self) -> None:
        self.jobs: list[ScheduledJob] = []

    def plan(self, sources: Optional[list[SourceConfig]] = None) -> list[ScheduledJob]:
        srcs = sources if sources is not None else load_config().enabled_sources()
        self.jobs = [
            ScheduledJob(s.name, s.cadence, _parse_cadence(s.cadence)) for s in srcs
        ]
        return self.jobs

    def run_job(self, job: ScheduledJob, fn: Callable[[], None]) -> bool:
        """Execute one job with failure isolation (AD-12). Returns success."""
        log = get_logger()
        try:
            fn()
            log.log(source=job.source_name, event="scheduled_run", status="ok")
            return True
        except Exception as exc:  # isolate: never let one job halt the scheduler
            log.log(source=job.source_name, event="scheduled_run",
                    status="error", error=str(exc))
            get_alerter().fire(
                AlertLevel.WARNING, f"Source job failed: {job.source_name}",
                source=job.source_name, error=str(exc),
            )
            return False

    def start_apscheduler(self, job_fns):  # pragma: no cover - needs the dep + loop
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
        except ImportError as exc:
            raise RuntimeError(
                "apscheduler not installed. `pip install legal-intel[full]`"
            ) from exc
        sched = BackgroundScheduler()
        for job in self.plan():
            fn = job_fns.get(job.source_name)
            if fn and job.interval_seconds:
                sched.add_job(fn, IntervalTrigger(seconds=job.interval_seconds),
                              id=job.source_name)
        sched.start()
        return sched
