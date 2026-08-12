from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from signalsift.fetch import FetchError, fetch_bytes, fetch_rss
from signalsift.models import NormalizedItem, SourceConfig


LOGGER = logging.getLogger(__name__)
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
CISA_CATALOG_URL = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"


class AdapterError(FetchError):
    """Raised when a source-specific response cannot be normalized safely."""


Adapter = Callable[..., tuple[NormalizedItem, ...]]


def fetch_cisa_kev(
    source: SourceConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[NormalizedItem, ...]:
    if source.type != "json" or source.adapter != "cisa_kev":
        raise AdapterError(f"source {source.id!r} is not configured for cisa_kev")
    fetched = fetch_bytes(source.url, transport=transport)
    return parse_cisa_kev(fetched.content, source_id=source.id)


def parse_cisa_kev(content: bytes, *, source_id: str) -> tuple[NormalizedItem, ...]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"invalid CISA KEV JSON: {type(exc).__name__}") from exc
    if not isinstance(document, dict):
        raise AdapterError("invalid CISA KEV document: expected object")
    entries = document.get("vulnerabilities")
    if not isinstance(entries, list):
        raise AdapterError("invalid CISA KEV document: vulnerabilities must be a list")

    items: list[NormalizedItem] = []
    for index, value in enumerate(entries):
        try:
            items.append(_normalize_cisa_entry(value, source_id=source_id))
        except (TypeError, ValueError) as exc:
            LOGGER.warning("source=%s entry=%d skipped: %s", source_id, index, exc)
    if entries and not items:
        raise AdapterError("CISA KEV document contains no valid entries")
    return tuple(items)


def fetch_source(
    source: SourceConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[NormalizedItem, ...]:
    """Dispatch one configured source without dynamic module loading."""

    if source.adapter is not None:
        adapter = ADAPTERS.get(source.adapter)
        if adapter is None:  # Configuration validation should catch this first.
            raise AdapterError(f"unknown adapter: {source.adapter!r}")
        return adapter(source, transport=transport)
    if source.type == "rss":
        return fetch_rss(source, transport=transport)
    raise AdapterError(f"source {source.id!r} has no fetch implementation")


def _normalize_cisa_entry(value: Any, *, source_id: str) -> NormalizedItem:
    if not isinstance(value, dict):
        raise TypeError("expected object")
    cve_id = _required_text(value, "cveID").upper()
    if not CVE_PATTERN.fullmatch(cve_id):
        raise ValueError("invalid cveID")
    title = _required_text(value, "vulnerabilityName")
    published_at = _date_added(value)
    summary = _optional_text(value, "shortDescription")
    required_action = _optional_text(value, "requiredAction")
    vendor = _optional_text(value, "vendorProject")
    product = _optional_text(value, "product")

    content_parts = [
        f"Vendor: {vendor}" if vendor else "",
        f"Product: {product}" if product else "",
        f"Required action: {required_action}" if required_action else "",
    ]
    raw_metadata = {
        key: text
        for key, text in (
            ("vendor_project", vendor),
            ("product", product),
            ("known_ransomware_campaign_use", _optional_text(value, "knownRansomwareCampaignUse")),
            ("due_date", _optional_text(value, "dueDate")),
            ("notes", _optional_text(value, "notes")),
        )
        if text
    }
    return NormalizedItem(
        id=cve_id,
        source_id=source_id,
        title=title,
        url=f"{CISA_CATALOG_URL}?{urlencode({'search_api_fulltext': cve_id})}",
        published_at=published_at,
        summary=summary,
        content=" ".join(part for part in content_parts if part),
        external_ids=(cve_id,),
        raw_metadata=raw_metadata,
    )


def _date_added(value: Mapping[str, Any]) -> datetime:
    text = _required_text(value, "dateAdded")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("invalid dateAdded") from exc
    return parsed.replace(tzinfo=UTC)


def _required_text(value: Mapping[str, Any], key: str) -> str:
    text = _optional_text(value, key)
    if not text:
        raise ValueError(f"missing or invalid {key}")
    return text


def _optional_text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise TypeError(f"invalid {key}")
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character for character in raw
    )
    return " ".join(without_controls.split())


ADAPTERS: Mapping[str, Adapter] = {
    "cisa_kev": fetch_cisa_kev,
}
