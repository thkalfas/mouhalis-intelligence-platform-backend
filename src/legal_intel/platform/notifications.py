"""Notifications: real-time Slack alerts + a once-per-run email digest (FR-20).

This is the delivery layer behind :class:`legal_intel.platform.alerting.Alerter`.
``__main__`` builds a :class:`NotificationRouter` from ``config/alerting.yaml`` and
attaches it as the alerter's dispatch, so every ``get_alerter().fire(...)`` call in
the pipeline routes here:

  * Slack — posted in real time (1-by-1) for events at/above ``slack.min_level``,
    minus ``digest_only_categories`` (so routine per-item rejects never flood the
    channel). CRITICAL always pings (unless Slack is disabled).
  * Email — every fired event is buffered; ``send_digest`` emits one summary
    email at the end of the run (the daily cron => one digest/day).

Routing, levels, recipients, and thresholds are all data (``alerting.yaml``).
Secrets (webhook URL, email key/SMTP password) come from env vars only.

Network is a seam: Slack/Resend POSTs go through an injectable ``Poster`` and SMTP
through an injectable sender, so tests run fully offline and never import httpx.
Missing secrets degrade to a logged no-op — they never crash a run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

import yaml
from pydantic import BaseModel, Field

from ..core.config import config_dir
from .alerting import AlertLevel
from .logging import get_logger

_LEVEL_RANK = {AlertLevel.INFO: 0, AlertLevel.WARNING: 1, AlertLevel.CRITICAL: 2}
_LEVEL_EMOJI = {AlertLevel.INFO: ":information_source:",
                AlertLevel.WARNING: ":warning:",
                AlertLevel.CRITICAL: ":rotating_light:"}


def _rank(level: str | AlertLevel) -> int:
    lvl = AlertLevel(level) if not isinstance(level, AlertLevel) else level
    return _LEVEL_RANK[lvl]


# --------------------------------------------------------------------------- #
# Config (typed, loaded from config/alerting.yaml — safe defaults if absent)
# --------------------------------------------------------------------------- #
class SlackConfig(BaseModel):
    enabled: bool = True
    webhook_url_env: str = "SLACK_WEBHOOK_URL"
    channel: str = ""
    min_level: str = "warning"
    digest_only_categories: list[str] = Field(default_factory=lambda: ["item_skip"])
    mention_on_critical: str = ""
    dedupe_within_run: bool = True


class ResendConfig(BaseModel):
    api_key_env: str = "RESEND_API_KEY"
    base_url: str = "https://api.resend.com"


class SmtpConfig(BaseModel):
    host_env: str = "SMTP_HOST"
    port: int = 587
    user_env: str = "SMTP_USER"
    password_env: str = "SMTP_PASSWORD"
    starttls: bool = True


class EmailConfig(BaseModel):
    enabled: bool = True
    provider: str = "resend"  # resend | smtp
    cadence: str = "daily"
    recipients: list[str] = Field(default_factory=list)
    from_: str = Field("", alias="from")
    subject_prefix: str = "[Mouhalis Legal Intel]"
    min_level: str = "info"
    resend: ResendConfig = Field(default_factory=ResendConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)

    model_config = {"populate_by_name": True}


class ThresholdsConfig(BaseModel):
    cost_daily_usd: float = 5.0


class AlertingConfig(BaseModel):
    enabled: bool = True
    slack: SlackConfig = Field(default_factory=SlackConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)


def load_alerting_config() -> AlertingConfig:
    """Parse ``config/alerting.yaml``; return all-defaults (disabled channels are
    still safe no-ops) when the file is absent so offline runs are unaffected."""
    path = config_dir() / "alerting.yaml"
    if not path.exists():
        return AlertingConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config {path} must be a mapping at top level")
    return AlertingConfig(**data)


# --------------------------------------------------------------------------- #
# Network seams (default impls lazy-import httpx / use stdlib smtplib)
# --------------------------------------------------------------------------- #
class Poster(Protocol):
    def __call__(self, url: str, payload: dict, headers: dict[str, str]) -> int: ...


def _httpx_poster(url: str, payload: dict, headers: dict[str, str]) -> int:
    import httpx  # lazy — only the real poster needs it

    resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
    return resp.status_code


class EmailSender(Protocol):
    def send(self, *, sender: str, to: list[str], subject: str,
             text: str, html: str) -> bool: ...


# --------------------------------------------------------------------------- #
# Events + run summary
# --------------------------------------------------------------------------- #
@dataclass
class AlertEvent:
    level: AlertLevel
    message: str
    category: str
    source: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceOutcome:
    source: str
    status: str
    persisted: int
    errors: int
    note: str = ""


@dataclass
class RunSummary:
    started_at: datetime
    finished_at: datetime
    sources: list[str] = field(default_factory=list)
    outcomes: list[SourceOutcome] = field(default_factory=list)
    ingested: int = 0
    persisted: int = 0
    errors: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #
class SlackNotifier:
    def __init__(self, cfg: SlackConfig, poster: Optional[Poster] = None) -> None:
        self._cfg = cfg
        self._poster = poster or _httpx_poster
        self._warned_missing = False

    def _webhook(self) -> str:
        return os.environ.get(self._cfg.webhook_url_env, "").strip()

    def format(self, level: AlertLevel, message: str, source: str) -> str:
        emoji = _LEVEL_EMOJI[level]
        head = f"{emoji} *{level.value.upper()}*"
        if level is AlertLevel.CRITICAL and self._cfg.mention_on_critical:
            head = f"{self._cfg.mention_on_critical} {head}"
        tail = f"  _(source: {source})_" if source and source != "alerting" else ""
        return f"{head} — {message}{tail}"

    def post(self, level: AlertLevel, message: str, source: str) -> bool:
        url = self._webhook()
        if not url:
            if not self._warned_missing:
                get_logger().log(source="alerting", event="slack", status="skipped",
                                 error=f"{self._cfg.webhook_url_env} not set")
                self._warned_missing = True
            return False
        try:
            code = self._poster(url, {"text": self.format(level, message, source)},
                                {"Content-Type": "application/json"})
        except Exception as exc:  # never let alert delivery break a run
            get_logger().log(source="alerting", event="slack", status="error",
                             error=str(exc)[:300])
            return False
        ok = 200 <= code < 300
        get_logger().log(source="alerting", event="slack",
                         status="sent" if ok else "error",
                         error=None if ok else f"HTTP {code}")
        return ok


# --------------------------------------------------------------------------- #
# Email digest
# --------------------------------------------------------------------------- #
class ResendSender:
    def __init__(self, cfg: ResendConfig, poster: Optional[Poster] = None) -> None:
        self._cfg = cfg
        self._poster = poster or _httpx_poster

    def send(self, *, sender: str, to: list[str], subject: str,
             text: str, html: str) -> bool:
        key = os.environ.get(self._cfg.api_key_env, "").strip()
        if not key:
            get_logger().log(source="alerting", event="email", status="skipped",
                             error=f"{self._cfg.api_key_env} not set")
            return False
        payload = {"from": sender, "to": to, "subject": subject,
                   "text": text, "html": html}
        try:
            code = self._poster(f"{self._cfg.base_url.rstrip('/')}/emails", payload,
                                {"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json"})
        except Exception as exc:
            get_logger().log(source="alerting", event="email", status="error",
                             error=str(exc)[:300])
            return False
        ok = 200 <= code < 300
        get_logger().log(source="alerting", event="email",
                         status="sent" if ok else "error",
                         error=None if ok else f"HTTP {code}")
        return ok


class SmtpSender:  # pragma: no cover - exercised via integration, not unit tests
    def __init__(self, cfg: SmtpConfig) -> None:
        self._cfg = cfg

    def send(self, *, sender: str, to: list[str], subject: str,
             text: str, html: str) -> bool:
        import smtplib
        from email.message import EmailMessage

        host = os.environ.get(self._cfg.host_env, "").strip()
        if not host:
            get_logger().log(source="alerting", event="email", status="skipped",
                             error=f"{self._cfg.host_env} not set")
            return False
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(host, self._cfg.port, timeout=30) as srv:
                if self._cfg.starttls:
                    srv.starttls()
                user = os.environ.get(self._cfg.user_env, "").strip()
                pwd = os.environ.get(self._cfg.password_env, "").strip()
                if user and pwd:
                    srv.login(user, pwd)
                srv.send_message(msg)
        except Exception as exc:
            get_logger().log(source="alerting", event="email", status="error",
                             error=str(exc)[:300])
            return False
        get_logger().log(source="alerting", event="email", status="sent")
        return True


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_digest(summary: RunSummary, events: list[AlertEvent],
                 subject_prefix: str) -> tuple[str, str, str]:
    """Return ``(subject, text, html)`` for the run digest."""
    crit = [e for e in events if e.level is AlertLevel.CRITICAL]
    warn = [e for e in events if e.level is AlertLevel.WARNING]
    date = summary.finished_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if crit:
        flag = f"\N{LARGE RED CIRCLE} {len(crit)} critical"
    elif summary.errors or warn:
        flag = f"\N{WARNING SIGN} {summary.errors} errors"
    else:
        flag = "OK"
    subject = (f"{subject_prefix} Daily digest — {date} — "
               f"{summary.persisted} new, {flag}")

    by_class = ", ".join(f"{k}:{v}" for k, v in sorted(summary.by_class.items())) or "—"

    # ---- plain text ----
    lines = [
        f"Legal Intelligence — run digest ({date})",
        f"Window: {_fmt_ts(summary.started_at)} -> {_fmt_ts(summary.finished_at)}",
        "",
        f"Sources run : {len(summary.sources)}  ({', '.join(summary.sources) or '—'})",
        f"Ingested    : {summary.ingested}",
        f"New items   : {summary.persisted}   (by class: {by_class})",
        f"Errors      : {summary.errors}",
        f"Cost        : ${summary.cost_usd:.4f}",
        "",
        "Per source:",
    ]
    for o in summary.outcomes:
        lines.append(f"  - {o.source}: {o.status} — {o.persisted} new, "
                     f"{o.errors} errors. {o.note}")
    if crit or warn:
        lines += ["", "Alerts this run:"]
        for e in crit + warn:
            lines.append(f"  [{e.level.value.upper()}] {e.message}"
                         + (f"  (source: {e.source})" if e.source else ""))
    else:
        lines += ["", "No alerts this run."]
    text = "\n".join(lines)

    # ---- html ----
    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    rows = "".join(
        f"<tr><td style='padding:4px 10px'>{esc(o.source)}</td>"
        f"<td style='padding:4px 10px'>{esc(o.status)}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{o.persisted}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{o.errors}</td>"
        f"<td style='padding:4px 10px'>{esc(o.note)}</td></tr>"
        for o in summary.outcomes
    )
    alerts_html = ""
    if crit or warn:
        items = "".join(
            f"<li><b>{e.level.value.upper()}</b> — {esc(e.message)}"
            + (f" <i>(source: {esc(e.source)})</i>" if e.source else "")
            + "</li>"
            for e in crit + warn
        )
        alerts_html = f"<h3>Alerts this run</h3><ul>{items}</ul>"
    else:
        alerts_html = "<p style='color:#2e7d32'>No alerts this run.</p>"

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#222;max-width:680px">
  <h2 style="margin:0 0 4px">Legal Intelligence — run digest</h2>
  <p style="color:#666;margin:0 0 16px">{esc(_fmt_ts(summary.started_at))} &rarr; {esc(_fmt_ts(summary.finished_at))}</p>
  <table style="border-collapse:collapse;margin-bottom:8px">
    <tr><td style="padding:2px 10px;color:#666">Sources run</td><td style="padding:2px 10px"><b>{len(summary.sources)}</b> ({esc(', '.join(summary.sources) or '—')})</td></tr>
    <tr><td style="padding:2px 10px;color:#666">Ingested</td><td style="padding:2px 10px">{summary.ingested}</td></tr>
    <tr><td style="padding:2px 10px;color:#666">New items</td><td style="padding:2px 10px"><b>{summary.persisted}</b> (by class: {esc(by_class)})</td></tr>
    <tr><td style="padding:2px 10px;color:#666">Errors</td><td style="padding:2px 10px">{summary.errors}</td></tr>
    <tr><td style="padding:2px 10px;color:#666">Cost</td><td style="padding:2px 10px">${summary.cost_usd:.4f}</td></tr>
  </table>
  <h3>Per source</h3>
  <table style="border-collapse:collapse;font-size:14px;border:1px solid #eee">
    <tr style="background:#f5f5f5"><th style="padding:4px 10px;text-align:left">Source</th><th style="padding:4px 10px;text-align:left">Status</th><th style="padding:4px 10px">New</th><th style="padding:4px 10px">Errors</th><th style="padding:4px 10px;text-align:left">Note</th></tr>
    {rows}
  </table>
  {alerts_html}
  <p style="color:#999;font-size:12px;margin-top:20px">Automated digest from the Legal Intelligence collection pipeline.</p>
</div>"""
    return subject, text, html


# --------------------------------------------------------------------------- #
# Router — the Alerter dispatch: real-time Slack + digest buffer
# --------------------------------------------------------------------------- #
class NotificationRouter:
    def __init__(self, cfg: AlertingConfig, *,
                 slack_poster: Optional[Poster] = None,
                 email_sender: Optional[EmailSender] = None) -> None:
        self._cfg = cfg
        self._slack = SlackNotifier(cfg.slack, poster=slack_poster)
        self._email_sender = email_sender or self._build_email_sender()
        self.events: list[AlertEvent] = []
        self._sent_keys: set[tuple] = set()

    def _build_email_sender(self) -> EmailSender:
        if self._cfg.email.provider == "smtp":
            return SmtpSender(self._cfg.email.smtp)
        return ResendSender(self._cfg.email.resend)

    # -- the dispatch callable (AlertLevel, str, dict) -> None --------------- #
    def __call__(self, level: AlertLevel, message: str, context: dict) -> None:
        ev = AlertEvent(
            level=level, message=message,
            category=str(context.get("category", "")),
            source=str(context.get("source", "")),
            context=dict(context),
        )
        self.events.append(ev)
        if self._cfg.enabled and self._cfg.slack.enabled and self._slack_worthy(ev):
            key = (ev.source, ev.category, ev.message)
            if self._cfg.slack.dedupe_within_run and key in self._sent_keys:
                return
            self._sent_keys.add(key)
            self._slack.post(ev.level, ev.message, ev.source)

    def _slack_worthy(self, ev: AlertEvent) -> bool:
        if _rank(ev.level) < _rank(self._cfg.slack.min_level):
            return False
        if ev.category and ev.category in self._cfg.slack.digest_only_categories:
            return False
        return True

    # -- end-of-run digest -------------------------------------------------- #
    def send_digest(self, summary: RunSummary) -> bool:
        email = self._cfg.email
        if not (self._cfg.enabled and email.enabled) or not email.recipients:
            return False
        highest = max((_rank(e.level) for e in self.events), default=0)
        if highest < _rank(email.min_level):
            get_logger().log(source="alerting", event="digest", status="skipped",
                             error="below min_level, nothing to report")
            return False
        subject, text, html = build_digest(summary, self.events, email.subject_prefix)
        return self._email_sender.send(
            sender=email.from_, to=list(email.recipients),
            subject=subject, text=text, html=html)


def make_router() -> NotificationRouter:
    return NotificationRouter(load_alerting_config())
