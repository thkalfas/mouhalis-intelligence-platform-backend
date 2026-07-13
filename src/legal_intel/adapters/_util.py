"""Small shared helpers for Tier-1 adapters (date parsing, RSS, dates window)."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Parse an ISO-ish date/datetime string to a date; None if unparseable.
    Handles ``2026-07-08``, ``2026-07-08T00:00:00`` and trailing ``Z``."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text[: len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    # Last resort: leading YYYY-MM-DD.
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    return None


# RFC-822 dates used by RSS 2.0, e.g. "Mon, 06 Jul 2026 09:00:00 +0000".
def parse_rfc822_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    return dt.date() if dt else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Namespaces stripped so callers can use plain tag names.
def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 / Atom into a list of ``{title, link, guid, pubDate,
    category, summary}`` dicts. Tolerant of either dialect."""
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []

    # RSS: channel/item ; Atom: feed/entry
    nodes = [n for n in root.iter() if strip_ns(n.tag) in ("item", "entry")]
    for node in nodes:
        rec: dict[str, str] = {}
        for child in node:
            tag = strip_ns(child.tag)
            if tag == "link":
                # Atom links carry the url in @href; RSS in text.
                rec["link"] = child.get("href") or (child.text or "").strip()
            elif tag in ("title", "guid", "id", "pubDate", "published",
                         "updated", "category", "summary", "description"):
                key = {"id": "guid", "published": "pubDate", "updated": "pubDate",
                       "description": "summary"}.get(tag, tag)
                rec.setdefault(key, (child.text or "").strip() or child.get("term", ""))
        items.append(rec)
    return items
