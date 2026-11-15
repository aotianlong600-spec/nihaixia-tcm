"""Shared Stage 0 provenance, orthogonal status, and source-span ledger checks."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CATALOG_PATH = ROOT / "brain_data" / "source_catalog.json"

GENERATION_STATUSES = {"auto", "assisted", "manual"}
EVIDENCE_STATUSES = {"unlinked", "anchored", "verified", "conflicted"}
REVIEW_STATUSES = {"pending", "needs_changes", "approved", "rejected"}
RISK_LEVELS = {"standard", "high_risk", "emergency"}
CONTENT_ROLES = (
    "source_quote",
    "ni_teaching",
    "other_annotations",
    "collation_notes",
    "organizer_summary",
)


def normalize_quote_text(text: str) -> str:
    """Strip layout whitespace and punctuation noise only for substring matching."""
    return re.sub(r"\s+", "", text or "")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def load_source_catalog() -> dict[str, dict]:
    data = json.loads(SOURCE_CATALOG_PATH.read_text(encoding="utf-8"))
    return {item["source_id"]: item for item in data.get("sources", [])}


def load_pages_index(jsonl_path: Path) -> dict[str, dict]:
    pages: dict[str, dict] = {}
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pages[row["page_id"]] = row
    return pages


def validate_orthogonal_statuses(record: dict) -> list[str]:
    errors: list[str] = []
    if record.get("generation_status") not in GENERATION_STATUSES:
        errors.append(f"invalid generation_status: {record.get('generation_status')!r}")
    if record.get("evidence_status") not in EVIDENCE_STATUSES:
        errors.append(f"invalid evidence_status: {record.get('evidence_status')!r}")
    if record.get("review_status") not in REVIEW_STATUSES:
        errors.append(f"invalid review_status: {record.get('review_status')!r}")
    if record.get("risk_level") not in RISK_LEVELS:
        errors.append(f"invalid risk_level: {record.get('risk_level')!r}")
    if record.get("risk_level") in {"high_risk", "emergency"}:
        if not str(record.get("safety_warning", "")).strip():
            errors.append("high_risk or emergency record must include non-empty safety_warning")
    if record.get("generation_status") == "auto" and record.get("review_status") == "approved":
        errors.append("auto-generated record cannot be marked approved directly")
    return errors


def validate_content_layers(record: dict) -> list[str]:
    errors: list[str] = []
    layers = record.get("content_layers")
    if not isinstance(layers, dict):
        return ["missing content_layers object"]
    for role in CONTENT_ROLES:
        if role not in layers or not isinstance(layers[role], list):
            errors.append(f"content_layers.{role} must be a list")
    return errors


def validate_source_span(
    span: dict,
    sources_by_id: dict[str, dict],
    pages_by_id: dict[str, dict],
) -> list[str]:
    errors: list[str] = []
    source_id = span.get("source_id", "")
    page_id = span.get("page_id", "")
    pdf_page = span.get("pdf_page")
    quote = span.get("quote", "")

    if source_id not in sources_by_id:
        return [f"unknown source_id: {source_id!r}"]
    if page_id not in pages_by_id:
        return [f"unknown page_id: {page_id!r}"]

    page = pages_by_id[page_id]
    if page.get("source_id") != source_id:
        errors.append(f"page {page_id} belongs to {page.get('source_id')}, not {source_id}")
    if page.get("pdf_page") != pdf_page:
        errors.append(f"page {page_id} has pdf_page={page.get('pdf_page')}, got {pdf_page}")

    norm_quote = normalize_quote_text(quote)
    if len(norm_quote) < 2:
        errors.append(f"quote too short on {page_id}")
    else:
        haystack = normalize_quote_text(
            "\n".join(
                [
                    page.get("body_text", ""),
                    page.get("raw_text", ""),
                    "\n".join(page.get("footnotes", [])),
                ]
            )
        )
        if norm_quote not in haystack:
            errors.append(f"quote not found verbatim on {page_id}: {quote[:40]!r}")

    if span.get("quote_sha256"):
        expected = sha256_text(quote)
        if span["quote_sha256"] != expected:
            errors.append(f"quote_sha256 mismatch on {page_id}")
    return errors


def validate_record_provenance(
    record: dict,
    sources_by_id: dict[str, dict],
    pages_by_id: dict[str, dict],
) -> list[str]:
    errors = validate_orthogonal_statuses(record)
    errors.extend(validate_content_layers(record))
    spans = record.get("source_spans", [])
    if record.get("evidence_status") == "verified" or record.get("review_status") == "approved":
        if not spans:
            errors.append("verified/approved record requires at least one source_span")
    if record.get("evidence_status") == "anchored" and not spans:
        errors.append("anchored record requires at least one source_span")
    for span in spans:
        errors.extend(validate_source_span(span, sources_by_id, pages_by_id))
    return errors
