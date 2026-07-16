"""Notion write-mapping (Story 0.5 provisioning) — pure, offline."""
from __future__ import annotations

from datetime import date, datetime, timezone

from legal_intel.core.models import (ActionItem, ClassReasoning, ContentClass,
                                     DecidedBy, Interpretation, Item, ItemStatus,
                                     SourceLink)
from legal_intel.core.notion_gateway import LocalJSONBackend, NotionGateway, to_payload
from legal_intel.core.notion_mapping import item_to_children, item_to_properties

_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _class_a() -> Item:
    return Item(
        source_id="32026R0001", source_name="EUR-Lex", title="Κανονισμός ιχνηλασιμότητας",
        type="Regulation", authority="European Commission", jurisdiction="EU",
        date_published=date(2026, 7, 8), date_effective=date(2026, 9, 1),
        url="https://eur-lex/CELEX", language="el", topics=["tobacco_traceability"],
        content_class=ContentClass.A,
        class_reasoning=ClassReasoning(decided_by=DecidedBy.RULE,
                                       detail="KAD match", rule_id="kad_direct_mention"),
        sector_touchpoints=["tobacco_wholesale"], action_signal="monitor",
        specialist_needed=False, full_text="πλήρες κείμενο " * 500, hash="h1",
        interpretation=Interpretation(
            summary="σύνοψη", what_changed_before="πριν", what_changed_after="μετά",
            what_changed_delta="δ", entry_into_force="2026-09-01",
            actions_required=[ActionItem(action="Αναβάθμιση WMS", owner_role="IT",
                                         deadline="2026-08-01", priority="high")]),
        interpretation_confidence=0.72,
        additional_sources=[SourceLink(source="kodiko.gr", url="https://kodiko/1",
                                       collected_at=_NOW)],
        external_commentary="σχόλιο", status=ItemStatus.CLASS_A_DRAFT_INTERPRETATION,
        collected_at=_NOW, draft_created_at=_NOW, page_id="p1",
    )


def test_class_a_properties_shape():
    p = item_to_properties(_class_a())
    assert p["Title"]["title"][0]["text"]["content"] == "Κανονισμός ιχνηλασιμότητας"
    assert p["Status"]["select"]["name"] == "Class A - Draft Interpretation"
    assert p["Content Class"]["select"]["name"] == "A"
    assert p["Topics"]["multi_select"] == [{"name": "tobacco_traceability"}]
    assert p["Date Published"]["date"]["start"] == "2026-07-08"
    assert p["URL"]["url"] == "https://eur-lex/CELEX"
    assert p["Decided By"]["select"]["name"] == "rule"
    assert "[rule: kad_direct_mention]" in p["Class Reasoning"]["rich_text"][0]["text"]["content"]
    assert p["Interpretation Summary"]["rich_text"][0]["text"]["content"] == "σύνοψη"
    assert "Έναρξη ισχύος: 2026-09-01" in p["Critical Dates"]["rich_text"][0]["text"]["content"]
    assert "Αναβάθμιση WMS" in p["Recommended Actions"]["rich_text"][0]["text"]["content"]
    assert p["Additional Sources"]["rich_text"][0]["text"]["content"].startswith("kodiko.gr — ")
    assert p["Upsert Key"]["rich_text"][0]["text"]["content"] == "EUR-Lex::32026R0001::h1"
    assert p["Specialist Needed"]["checkbox"] is False


def test_rich_text_truncated_to_2000():
    p = item_to_properties(_class_a())
    # External commentary is short; check the long-ish additional-sources/text caps.
    body = item_to_children(_class_a())
    assert all(len(b["paragraph"]["rich_text"][0]["text"]["content"]) <= 2000
               for b in body if b["type"] == "paragraph")


def test_class_a_body_has_disclaimer_and_text():
    blocks = item_to_children(_class_a())
    assert blocks[0]["type"] == "callout"
    assert "νομική συμβουλή" in blocks[0]["callout"]["rich_text"][0]["text"]["content"]
    assert any(b["type"] == "paragraph" for b in blocks)


def test_class_b_is_index_only_no_body():
    b = Item(source_id="x", source_name="Diavgeia", title="Ναυτιλιακά", type="Απόφαση",
             authority="ΥΝΑΝΠ", content_class=ContentClass.B, full_text=None,
             status=ItemStatus.CLASS_B_INDEXED, hash="hb")
    assert item_to_children(b) == []
    p = item_to_properties(b)
    assert p["Content Class"]["select"]["name"] == "B"
    assert "Interpretation Summary" not in p  # nothing to write


def test_human_fields_not_clobbered_when_absent():
    # A fresh pipeline Item has no reviewer/notes → those props are omitted, so a
    # reviewer's Notion edits survive a re-write.
    p = item_to_properties(_class_a())
    assert "Reviewer" not in p          # people fields never written by pipeline
    assert "Action Owner" not in p
    assert "Review Notes" not in p      # None → omitted
    assert "Client Action Status" not in p


def test_human_fields_written_when_present():
    item = _class_a()
    item.review_notes = "χρειάζεται διόρθωση"
    item.client_action_status = "Track Deadline"
    item.action_deadline = date(2026, 8, 15)
    p = item_to_properties(item)
    assert p["Review Notes"]["rich_text"][0]["text"]["content"] == "χρειάζεται διόρθωση"
    assert p["Client Action Status"]["select"]["name"] == "Track Deadline"
    assert p["Action Deadline"]["date"]["start"] == "2026-08-15"


def test_supersedes_relation_only_for_notion_ids():
    item = _class_a()
    item.supersedes = ["not-an-id", "39ec8c56f54c8107b43ff1880b78b877"]
    p = item_to_properties(item)
    assert p["Supersedes"]["relation"] == [{"id": "39ec8c56f54c8107b43ff1880b78b877"}]


def test_class_b_payload_roundtrips_through_gateway_strip():
    # to_payload strips B's text; Item.model_validate(payload) → mapping still fine.
    b = Item(source_id="x", source_name="Diavgeia", title="t", type="Απόφαση",
             authority="a", content_class=ContentClass.B, full_text="secret",
             status=ItemStatus.CLASS_B_INDEXED, hash="hb")
    payload = to_payload(b)
    assert payload["full_text"] is None
    round = Item.model_validate(payload)
    assert item_to_children(round) == []


def test_gateway_local_still_mints_ids():
    gw = NotionGateway(LocalJSONBackend())
    item = Item(source_id="x", source_name="EUR-Lex", title="t", type="r",
                authority="a", hash="h")
    out = gw.upsert_item(item)
    assert out.page_id and out.page_id.startswith("page_")
    # idempotent: same key reuses the page
    again = gw.upsert_item(Item(source_id="x", source_name="EUR-Lex", title="t2",
                                type="r", authority="a", hash="h"))
    assert again.page_id == out.page_id
    assert gw.count() == 1
