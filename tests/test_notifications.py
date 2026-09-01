"""FR-20 — Slack real-time alerts + email digest routing.

All offline: the network is a seam (fake Poster / fake EmailSender), so no httpx,
no SMTP, no secrets. Covers severity/category routing, in-run dedupe, missing-
secret no-ops, the digest builder, and end-of-run digest gating.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from legal_intel.platform.alerting import AlertLevel
from legal_intel.platform.notifications import (AlertingConfig, EmailConfig,
                                                NotificationRouter, RunSummary,
                                                SlackConfig, SourceOutcome,
                                                build_digest,
                                                load_alerting_config)


class FakePoster:
    def __init__(self, code: int = 200):
        self.calls: list[tuple] = []
        self._code = code

    def __call__(self, url, payload, headers):
        self.calls.append((url, payload, headers))
        return self._code


class FakeEmail:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, *, sender, to, subject, text, html):
        self.sent.append(dict(sender=sender, to=to, subject=subject,
                              text=text, html=html))
        return True


def _cfg(**slack_over) -> AlertingConfig:
    return AlertingConfig(
        slack=SlackConfig(**slack_over),
        email=EmailConfig(recipients=["ops@example.com"], **{"from": "a@b.co"}),
    )


def _summary() -> RunSummary:
    t = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
    return RunSummary(
        started_at=t, finished_at=t, sources=["EUR-Lex", "Διαύγεια"],
        outcomes=[SourceOutcome("EUR-Lex", "Success", 0, 0, "0/0 collected"),
                  SourceOutcome("Διαύγεια", "Success", 24, 0, "24/80 collected")],
        ingested=80, persisted=24, errors=0, by_class={"B": 5, "C": 19},
        cost_usd=0.039,
    )


# --------------------------------------------------------------------------- #
def test_config_loads_from_repo_yaml():
    cfg = load_alerting_config()
    assert cfg.enabled
    assert cfg.slack.digest_only_categories == ["item_skip"]
    assert "antonis.ventouris@reborrn.com" in cfg.email.recipients
    assert cfg.email.from_  # alias "from" parsed


def test_routing_by_level_and_category(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    poster = FakePoster()
    router = NotificationRouter(_cfg(), slack_poster=poster)

    router(AlertLevel.INFO, "fyi", {"source": "X"})               # below min_level
    router(AlertLevel.WARNING, "skip one", {"source": "X",
                                            "category": "item_skip"})  # digest-only
    router(AlertLevel.WARNING, "scraper broke", {"source": "ΦΕΚ"})  # → Slack
    router(AlertLevel.CRITICAL, "source down", {"source": "Διαύγεια"})  # → Slack

    assert len(poster.calls) == 2
    texts = [c[1]["text"] for c in poster.calls]
    assert any("scraper broke" in t for t in texts)
    assert any("CRITICAL" in t for t in texts)
    # but ALL four are buffered for the digest
    assert len(router.events) == 4


def test_dedupe_within_run(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    poster = FakePoster()
    router = NotificationRouter(_cfg(), slack_poster=poster)
    for _ in range(3):
        router(AlertLevel.WARNING, "same breakage", {"source": "ΦΕΚ"})
    assert len(poster.calls) == 1


def test_slack_noop_without_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    poster = FakePoster()
    router = NotificationRouter(_cfg(), slack_poster=poster)
    router(AlertLevel.CRITICAL, "boom", {"source": "X"})
    assert poster.calls == []          # no webhook => no post, no crash
    assert len(router.events) == 1     # still buffered for the digest


def test_mention_on_critical(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    poster = FakePoster()
    router = NotificationRouter(_cfg(mention_on_critical="<!channel>"),
                                slack_poster=poster)
    router(AlertLevel.CRITICAL, "down", {"source": "Διαύγεια"})
    assert poster.calls[0][1]["text"].startswith("<!channel>")


def test_build_digest_contents():
    events = []  # no alerts
    subject, text, html = build_digest(_summary(), events, "[Legal]")
    assert subject.startswith("[Legal]") and "24 new" in subject
    assert "EUR-Lex" in text and "Διαύγεια" in text
    assert "B:5, C:19" in text
    assert "No alerts this run" in text
    assert "<table" in html


def test_build_digest_lists_alerts():
    from legal_intel.platform.notifications import AlertEvent
    events = [AlertEvent(AlertLevel.CRITICAL, "Source 'X' failed", "source_failure", "X")]
    subject, text, html = build_digest(_summary(), events, "[Legal]")
    assert "critical" in subject.lower()
    assert "Source 'X' failed" in text
    assert "Source &#x27;X&#x27; failed" in html or "Source 'X' failed" in html


def test_send_digest_sends(monkeypatch):
    fake = FakeEmail()
    router = NotificationRouter(_cfg(), email_sender=fake)
    router(AlertLevel.WARNING, "something", {"source": "X"})
    assert router.send_digest(_summary()) is True
    assert fake.sent and fake.sent[0]["to"] == ["ops@example.com"]


def test_send_digest_gated_by_min_level():
    fake = FakeEmail()
    cfg = AlertingConfig(
        email=EmailConfig(recipients=["ops@example.com"], min_level="warning",
                          **{"from": "a@b.co"}))
    router = NotificationRouter(cfg, email_sender=fake)
    router(AlertLevel.INFO, "just fyi", {"source": "X"})   # nothing >= warning
    assert router.send_digest(_summary()) is False
    assert fake.sent == []


def test_send_digest_noop_without_recipients():
    fake = FakeEmail()
    cfg = AlertingConfig(email=EmailConfig(recipients=[], **{"from": "a@b.co"}))
    router = NotificationRouter(cfg, email_sender=fake)
    assert router.send_digest(_summary()) is False


def test_resend_sender_posts(monkeypatch):
    from legal_intel.platform.notifications import ResendConfig, ResendSender
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    poster = FakePoster(code=200)
    sender = ResendSender(ResendConfig(), poster=poster)
    ok = sender.send(sender="a@b.co", to=["x@y.z"], subject="s",
                     text="t", html="<p>t</p>")
    assert ok is True
    url, payload, headers = poster.calls[0]
    assert url.endswith("/emails")
    assert headers["Authorization"] == "Bearer re_test_key"
    assert payload["to"] == ["x@y.z"]


def test_resend_sender_noop_without_key(monkeypatch):
    from legal_intel.platform.notifications import ResendConfig, ResendSender
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    poster = FakePoster()
    sender = ResendSender(ResendConfig(), poster=poster)
    assert sender.send(sender="a@b.co", to=["x@y.z"], subject="s",
                       text="t", html="<p>t</p>") is False
    assert poster.calls == []
