#!/usr/bin/env python3
"""Notion workspace provisioning (Story 0.5, FR-17, spec §10).

Declares the System-of-Record schema as data (the four class-aware property groups,
the auxiliary databases, and the eight views) and provisions it. Idempotent:
re-running detects existing databases by title and does not duplicate them.

  python scripts/provision_notion.py            # local mode: writes data/notion_schema.json
  LEGAL_INTEL_NOTION_BACKEND=notion \
    NOTION_TOKEN=... NOTION_PARENT_PAGE=... \
    python scripts/provision_notion.py          # creates databases in Notion

The declarative SCHEMA below is the single source for both modes and for later
NotionApiBackend property mapping.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Declarative schema (spec §10). Property type vocabulary matches Notion's.
# --------------------------------------------------------------------------- #
LEGAL_INTELLIGENCE = {
    "title": "Legal Intelligence",
    "property_groups": {
        "always": {  # Group 1 — A, B, C
            "Title": "title", "Source ID": "rich_text", "Source": "select",
            "Type": "multi_select", "Authority": "select", "Jurisdiction": "select",
            "Date Published": "date", "Date Effective": "date", "Topics": "multi_select",
            "Content Class": "select", "Class Reasoning": "rich_text",
            "Confidence Score": "number", "Dedup Score": "number",
            "Original URL": "url", "Upsert Key": "rich_text", "Collected At": "created_time",
        },
        "full_text": {  # Group 2 — A + C only
            "Full Text": "child_page", "Language": "select", "Snippet": "rich_text",
        },
        "interpretation": {  # Group 3 — A only
            "Summary": "rich_text", "What Changed - Before": "rich_text",
            "What Changed - After": "rich_text", "What Changed - Delta": "rich_text",
            "Business Lines Affected": "multi_select",
            "Support Functions Affected": "multi_select",
            "Operational Impact": "rich_text", "Compliance New Obligations": "rich_text",
            "Compliance Lifted Obligations": "rich_text", "Actions Required": "child_page",
            "Entry Into Force": "date", "Transition End": "date",
            "Reporting Deadlines": "rich_text", "Cited Articles": "rich_text",
            "Related Events": "relation", "Requires Specialist Review": "checkbox",
            "Specialist Domain": "select", "Confidence Notes": "rich_text",
        },
        "review": {  # Group 4 — populated during human review
            "Interpretation Status": "select", "Reviewer": "people",
            "Review Started At": "date", "Review Completed At": "date",
            "Review Notes": "rich_text", "Client Action Status": "select",
            "Action Owner": "people", "Action Deadline": "date",
            "Reclassify Requested": "checkbox",
        },
    },
    "views": [
        "Recent items", "Pending Relevance Review", "Awaiting Dedup Confirmation",
        "Pending Interpretation Review", "Approved & Actionable", "By Topic",
        "Critical Deadlines", "Index Archive", "My Queue",
    ],
}

AUXILIARY = {
    "Reviewers Workload": ["Reviewer", "Current queue depth", "Avg time to review",
                           "Areas of expertise", "Available", "Max concurrent items"],
    "Ontology Reference": ["Topic ID", "Name GR", "Name EN", "Domain",
                           "Keywords GR", "Keywords EN", "Priority", "Sample Items"],
    "Interpretation Examples": ["Topic", "Original Item", "Interpretation",
                                "Notes", "Added by", "Date"],
    "Cost Ledger": ["Timestamp", "Stage", "Model", "Input Tokens", "Output Tokens",
                    "USD Cost", "Item", "Success", "Tag"],
}

SCHEMA = {"main": LEGAL_INTELLIGENCE, "auxiliary": AUXILIARY}


def provision_local() -> Path:
    out = Path(os.environ.get("LEGAL_INTEL_CONFIG", "config")).parent / "data" / "notion_schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(SCHEMA, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[local] Schema written to {out}")
    print(f"  main DB: {LEGAL_INTELLIGENCE['title']} "
          f"({sum(len(g) for g in LEGAL_INTELLIGENCE['property_groups'].values())} properties, "
          f"{len(LEGAL_INTELLIGENCE['views'])} views)")
    for name, props in AUXILIARY.items():
        print(f"  aux DB : {name} ({len(props)} properties)")
    return out


def provision_notion() -> None:  # pragma: no cover - needs token
    from notion_client import Client
    client = Client(auth=os.environ["NOTION_TOKEN"])
    parent = os.environ["NOTION_PARENT_PAGE"]
    existing = {
        b["title"][0]["plain_text"]
        for b in client.search(filter={"property": "object", "value": "database"}).get("results", [])
        if b.get("title")
    }
    for db_title in [LEGAL_INTELLIGENCE["title"], *AUXILIARY]:
        if db_title in existing:
            print(f"[notion] '{db_title}' already exists — skipping (idempotent).")
            continue
        print(f"[notion] Would create database '{db_title}' under parent {parent}.")
        # NOTE: concrete create_database property mapping is completed in Epic 0
        # Story 0.5 implementation against a live workspace; declared here as data.


def main() -> None:
    if os.environ.get("LEGAL_INTEL_NOTION_BACKEND", "local").lower() == "notion":
        provision_notion()
    else:
        provision_local()


if __name__ == "__main__":
    main()
