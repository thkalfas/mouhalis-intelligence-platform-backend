"""Commercial shared-inbox newsletter parser (Story 4.1, FR-3).

Tier-3 safety net & cross-validation: the legal team's commercial newsletters
(Qualex, NB Daily, taxheaven, δικηγορικά γραφεία, …) are BCC-forwarded to a
dedicated shared inbox (`legal-intel@…`). This adapter reads **only that inbox,
never a personal mailbox**, extracts the linked items, fetches their content, and
yields SourceRecords marked as a commercial source.

Because every commercial source carries `authority_rank: 3` in sources.yaml, a
commercial record can never win metadata over an official Source on merge (Epic 2
authority hierarchy) — its value is coverage + editorial, which is preserved in
`external_commentary`.

The mailbox itself is an injected ``MailboxReader`` seam: a lazy IMAP reader in
production, fixtures in tests — so this runs fully offline like every other
adapter. Link-content fetching goes through the shared Tier-1 ``HttpClient``.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional, Protocol

from ..core.config import SourceConfig
from ..core.models import SourceRecord
from ..platform.http import HttpClient
from ..platform.logging import get_logger
from .base import SourceAdapter
from ._util import now_utc

_URL_RX = re.compile(r"https?://[^\s\"'<>)]+")


# --------------------------------------------------------------------------- #
# Mailbox seam
# --------------------------------------------------------------------------- #
class MailboxReader(Protocol):
    """Yields email messages from exactly one mailbox. Implementations MUST be
    bound to the shared inbox only."""

    def fetch_messages(self) -> Iterable[Message]: ...


class ImapMailboxReader:  # pragma: no cover - needs network + credentials
    """Reads UNSEEN messages from the configured shared inbox over IMAP. Host,
    user, and password come from the secret store (env vars named in config).
    The user IS the shared-inbox address — there is no path to a personal one."""

    def __init__(self, host: str, user: str, password: str, mailbox: str = "INBOX"):
        self._host, self._user, self._password, self._mailbox = host, user, password, mailbox

    def fetch_messages(self) -> Iterable[Message]:
        import email
        import imaplib

        conn = imaplib.IMAP4_SSL(self._host)
        try:
            conn.login(self._user, self._password)
            conn.select(self._mailbox)
            _typ, data = conn.search(None, "UNSEEN")
            for num in data[0].split():
                _typ, msg_data = conn.fetch(num, "(RFC822)")
                yield email.message_from_bytes(msg_data[0][1])
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# HTML link extraction
# --------------------------------------------------------------------------- #
class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._href: Optional[str] = None
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = ""

    def handle_data(self, data):
        if self._href is not None:
            self._text += data

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, self._text.strip()))
            self._href = None


def _links_from_body(body: str, is_html: bool) -> list[tuple[str, str]]:
    if is_html:
        p = _LinkExtractor()
        p.feed(body)
        if p.links:
            return p.links
    # plain text (or HTML with no anchors) → bare URLs, no anchor text
    return [(m.group(0), "") for m in _URL_RX.finditer(body)]


def _message_body(msg: Message) -> tuple[str, bool]:
    """Return (body, is_html), preferring an HTML part."""
    html = plain = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html" and html is None:
                html = _decode(part)
            elif ctype == "text/plain" and plain is None:
                plain = _decode(part)
    else:
        payload = _decode(msg)
        if msg.get_content_type() == "text/html":
            html = payload
        else:
            plain = payload
    if html:
        return html, True
    return (plain or ""), False


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return part.get_payload() or ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class CommercialInboxAdapter(SourceAdapter):
    tier = 3

    def __init__(self, cfg: SourceConfig, http: Optional[HttpClient] = None,
                 *, reader: Optional[MailboxReader] = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.http = http or HttpClient()
        self._reader = reader
        self.log = get_logger()

    def _build_reader(self) -> Optional[MailboxReader]:
        import os

        o = self.cfg.options
        inbox = o.get("inbox_address")
        if not inbox:
            self.log.log(source=self.name, event="fetch", status="degraded",
                         error="no shared inbox_address configured — refusing to read")
            return None
        host = os.environ.get(o.get("imap_host_env", "IMAP_HOST"))
        password = os.environ.get(o.get("imap_password_env", "IMAP_PASSWORD"))
        if not host or not password:
            self.log.log(source=self.name, event="fetch", status="degraded",
                         error="IMAP credentials missing in secret store")
            return None
        return ImapMailboxReader(host, inbox, password)

    def fetch(self) -> Iterable[SourceRecord]:
        reader = self._reader or self._build_reader()
        if reader is None:
            return
        max_links = int(self.cfg.options.get("max_links_per_email", 20))
        allow = self.cfg.options.get("link_allow_domains") or []
        for msg in reader.fetch_messages():
            yield from self._records_from_message(msg, max_links, allow)

    def _records_from_message(self, msg: Message, max_links: int,
                              allow: list) -> Iterable[SourceRecord]:
        subject = str(msg.get("Subject", "")).strip()
        sender = str(msg.get("From", ""))
        source_name = self._source_for_sender(sender)
        date_pub = None
        raw_date = msg.get("Date")
        if raw_date:
            try:
                date_pub = parsedate_to_datetime(raw_date).date()
            except (TypeError, ValueError):
                date_pub = None

        body, is_html = _message_body(msg)
        # The newsletter's own editorial (its text) is commentary, never metadata.
        commentary = re.sub(r"\s+", " ", _html_to_text(body) if is_html else body).strip()
        commentary = commentary[:1000] or None

        seen: set[str] = set()
        emitted = 0
        for href, text in _links_from_body(body, is_html):
            if emitted >= max_links:
                break
            if not href.startswith("http") or href in seen:
                continue
            if allow and not any(dom in href for dom in allow):
                continue
            seen.add(href)
            emitted += 1
            yield self._record(href, text or subject, source_name, date_pub, commentary)

    def _record(self, url, title, source_name, date_pub, commentary) -> SourceRecord:
        raw_body = content_type = None
        try:
            resp = self.http.get(url, accept="text/html")
            raw_body, content_type = resp.content, resp.content_type or "text/html"
        except Exception as exc:  # link content is best-effort
            self.log.log(source=self.name, event="fetch_link", status="degraded",
                         error=str(exc), item_id=url)
        return SourceRecord(
            source_id=url,
            source_name=source_name,
            title=title or url,
            type=self.cfg.options.get("default_type", "Newsletter"),
            authority=source_name,
            date_published=date_pub,
            url=url,
            raw_body=raw_body,
            content_type=content_type,
            language=self.cfg.options.get("language"),
            raw_metadata={"commercial": True, "external_commentary": commentary},
            collected_at=now_utc(),
        )

    def _source_for_sender(self, sender: str) -> str:
        low = sender.lower()
        for needle, name in (self.cfg.options.get("sender_source_map") or {}).items():
            if needle.lower() in low:
                return name
        return self.cfg.options.get("default_source_name", "Commercial Newsletter")


def _html_to_text(html: str) -> str:
    # Reuse the extraction module's HTML→text (avoids a second parser impl).
    from ..pipeline.extract import extract_text

    return extract_text(html, "text/html").text
