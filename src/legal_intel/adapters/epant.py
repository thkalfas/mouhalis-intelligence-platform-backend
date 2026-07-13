"""Επιτροπή Ανταγωνισμού (ΕπΑντ) scraper (Story 3.3, FR-2).

**The preferred path for ΕπΑντ is the Δι@ύγεια Tier-1 adapter** (§5.2.3): configure
the `Διαύγεια` source with the ΕπΑντ organization UID and it is captured there
daily, with no scraping. This direct site scraper is the *weekly cross-check*
for the rare decision that never reaches Δι@ύγεια — it inherits all Tier-2
politeness and breakage alerting from ``HtmlListScraper``. Its config should set
a weekly cadence to keep the direct hits minimal.
"""
from __future__ import annotations

from .tier2 import HtmlListScraper


class EpantScraper(HtmlListScraper):
    """Direct epant.gr apofaseis-gnomodotiseis cross-check. Behaviour is entirely
    config-driven (row selectors, id/date regexes) — see sources.yaml options."""
