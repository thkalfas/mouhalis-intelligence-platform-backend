"""Lookback window — skip Items published before the cutoff (config max_age_days)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from legal_intel.adapters.base import SourceAdapter
from legal_intel.core.models import SourceRecord

_TODAY = date(2026, 7, 21)


class _DatedAdapter(SourceAdapter):
    name = "Dated"
    tier = 1

    def __init__(self, dates):
        self._dates = dates  # list of Optional[date]

    def fetch(self) -> Iterable[SourceRecord]:
        for i, dp in enumerate(self._dates):
            yield SourceRecord(
                source_id=f"KAD-{i}", source_name="EUR-Lex",
                title="ΚΑΔ 46.35 μέτρο", type="Regulation", authority="EU",
                date_published=dp, url=f"https://x/{i}",
                full_text="ΚΑΔ 46.35 σχετικό κείμενο", language="el",
            )


def test_old_items_filtered_recent_passes(runner):
    runner.cfg.max_age_days = 180
    dates = [
        _TODAY - timedelta(days=10),    # recent → pass
        _TODAY - timedelta(days=400),   # old → filtered by the window
    ]
    report = runner.run(_DatedAdapter(dates), now=_TODAY)
    assert report.ingested == 2
    assert report.filtered == 1
    assert report.persisted == 1


def test_undated_is_not_filtered_by_window(runner):
    # The window passes undated Items (filtered==0); the normalize data-quality
    # gate handles missing dates separately, so it never persists here.
    runner.cfg.max_age_days = 180
    report = runner.run(_DatedAdapter([None]), now=_TODAY)
    assert report.filtered == 0


def test_zero_disables_filter(runner):
    runner.cfg.max_age_days = 0
    report = runner.run(_DatedAdapter([_TODAY - timedelta(days=5000)]), now=_TODAY)
    assert report.filtered == 0
    assert report.persisted == 1


def test_default_window_is_180(monkeypatch):
    from legal_intel.core.config import load_config, reload_config
    reload_config()
    assert load_config().max_age_days == 180
