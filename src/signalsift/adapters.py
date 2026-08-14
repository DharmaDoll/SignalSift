from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from signalsift.fetch import EXTERNAL_ID_PATTERN, FetchError, fetch_bytes, fetch_rss
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


def fetch_flatt_blog(
    source: SourceConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[NormalizedItem, ...]:
    if source.type != "html" or source.adapter != "flatt_blog":
        raise AdapterError(f"source {source.id!r} is not configured for flatt_blog")
    fetched = fetch_bytes(source.url, transport=transport)
    return parse_flatt_blog(
        fetched.content,
        source_id=source.id,
        source_url=source.url,
    )


def parse_flatt_blog(
    content: bytes,
    *,
    source_id: str,
    source_url: str,
) -> tuple[NormalizedItem, ...]:
    """Parse only the article cards on the Flatt blog index page."""

    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterError("invalid Flatt blog HTML encoding") from exc
    parser = _FlattIndexParser()
    try:
        parser.feed(document)
        parser.close()
    except ValueError as exc:
        raise AdapterError(f"invalid Flatt blog HTML: {exc}") from exc
    if not parser.entries:
        raise AdapterError("Flatt blog HTML contains no archive entries")

    items: list[NormalizedItem] = []
    for index, entry in enumerate(parser.entries):
        try:
            items.append(
                _normalize_flatt_entry(
                    entry,
                    source_id=source_id,
                    source_url=source_url,
                )
            )
        except (TypeError, ValueError) as exc:
            LOGGER.warning("source=%s entry=%d skipped: %s", source_id, index, exc)
    if not items:
        raise AdapterError("Flatt blog HTML contains no valid entries")
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


def fetch_html_index(source: SourceConfig, *, transport: httpx.BaseTransport | None = None) -> tuple[NormalizedItem, ...]:
    fetched = fetch_bytes(source.url, transport=transport)
    return parse_html_index(fetched.content, source_id=source.id, source_url=source.url, adapter=source.adapter or "")


def parse_html_index(content: bytes, *, source_id: str, source_url: str, adapter: str) -> tuple[NormalizedItem, ...]:
    parser = _SimpleResearchParser(adapter)
    try:
        parser.feed(content.decode("utf-8"))
        parser.close()
    except UnicodeDecodeError as exc:
        raise AdapterError(f"invalid {adapter} HTML encoding") from exc
    if not parser.entries:
        raise AdapterError(f"{adapter} HTML contains no article cards")
    items = tuple(
        NormalizedItem(
            id=f"{source_id}:{urljoin(source_url, url)}", source_id=source_id, title=title, url=urljoin(source_url, url),
            published_at=None, summary="", content="", categories=(), external_ids=(),
            raw_metadata={"source_format": "html-index", "published_precision": "unknown"},
        )
        for title, url in parser.entries
    )
    return items


class _SimpleResearchParser(HTMLParser):
    def __init__(self, adapter: str) -> None:
        super().__init__(convert_charrefs=True)
        self.adapter = adapter
        self.entries: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_title: list[str] = []
        self._collect_title = False
        self._titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        if tag == "a" and self._is_article_href(href):
            self._current_href = href
            self._current_title = []
            track_title = attributes.get("data-page-track-value") or ""
            if track_title:
                self._current_title.append(track_title.rsplit(":", 1)[-1])
        if tag in {"p", "div"} and (attributes.get("fs-list-field") == "title" or "heading-style-h5" in (attributes.get("class") or "")):
            self._collect_title = True

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._current_href is not None:
            self._current_title.append(text)
        if self._collect_title:
            self._titles.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div"}:
            self._collect_title = False
        if tag == "a" and self._current_href is not None:
            title = " ".join(dict.fromkeys(self._current_title)).strip()
            if self.adapter in {"lakera_blog", "hiddenlayer_research"} and self._titles:
                title = self._titles.pop(0)
            if title:
                self.entries.append((title, self._current_href))
            self._current_href = None

    def _is_article_href(self, href: str) -> bool:
        href = urlsplit(href).path
        if self.adapter == "huntr_blog":
            return href.startswith("/huntr-") or href.startswith("/hunting-") or href.startswith("/inside-") or href.startswith("/pickle-") or href.startswith("/exposing-")
        if self.adapter == "lakera_blog":
            return href.startswith("/blog/")
        return href.startswith("/research/")


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
        categories=("CISA KEV", "Known Exploited Vulnerability"),
        external_ids=(cve_id,),
        raw_metadata={**raw_metadata, "published_precision": "date"},
    )


@dataclass(slots=True)
class _FlattIndexEntry:
    uuid: str | None
    published_date: str | None = None
    title: list[str] = field(default_factory=list)
    url: str | None = None
    summary: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


class _FlattIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[_FlattIndexEntry] = []
        self._entry: _FlattIndexEntry | None = None
        self._entry_section_depth = 0
        self._stack: list[tuple[str, frozenset[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = frozenset((attributes.get("class") or "").split())
        if tag == "section" and self._entry is None and "archive-entry" in classes:
            self._entry = _FlattIndexEntry(uuid=attributes.get("data-uuid"))
            self._entry_section_depth = 1
        elif tag == "section" and self._entry is not None:
            self._entry_section_depth += 1

        self._stack.append((tag, classes))
        if self._entry is None:
            return
        if tag == "a" and "entry-title-link" in classes:
            self._entry.url = attributes.get("href")
        elif tag == "time" and self._inside("archive-entry-header"):
            self._entry.published_date = attributes.get("datetime")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._entry is None or self._inside("script") or self._inside("style"):
            return
        if self._inside("entry-title-link"):
            self._entry.title.append(data)
        elif self._inside("entry-description"):
            self._entry.summary.append(data)
        elif self._inside("categories") and self._stack and self._stack[-1][0] == "a":
            self._entry.categories.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._entry is not None:
            self._entry_section_depth -= 1
            if self._entry_section_depth == 0:
                self.entries.append(self._entry)
                self._entry = None
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def _inside(self, class_or_tag: str) -> bool:
        return any(
            tag == class_or_tag or class_or_tag in classes
            for tag, classes in self._stack
        )


def _normalize_flatt_entry(
    entry: _FlattIndexEntry,
    *,
    source_id: str,
    source_url: str,
) -> NormalizedItem:
    uuid = _clean_text(entry.uuid)
    if not uuid or not uuid.isascii() or not uuid.isdigit():
        raise ValueError("missing or invalid data-uuid")
    title = _clean_text(" ".join(entry.title))
    if not title:
        raise ValueError("missing title")
    published_date = _clean_text(entry.published_date)
    try:
        published_at = datetime.strptime(published_date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError("missing or invalid published date") from exc
    url = _same_origin_https_url(entry.url, source_url)
    summary = _clean_text(" ".join(entry.summary))
    categories = tuple(
        dict.fromkeys(
            cleaned
            for value in entry.categories
            if (cleaned := _clean_text(value))
        )
    )
    external_ids = tuple(
        dict.fromkeys(
            match.upper()
            for match in EXTERNAL_ID_PATTERN.findall(
                " ".join((title, summary, *categories))
            )
        )
    )
    return NormalizedItem(
        id=f"hatenablog://entry/{uuid}",
        source_id=source_id,
        title=title,
        url=url,
        published_at=published_at,
        summary=summary,
        categories=categories,
        external_ids=external_ids,
        raw_metadata={"source_format": "html-index", "published_precision": "date"},
    )


def _same_origin_https_url(value: str | None, source_url: str) -> str:
    if not value:
        raise ValueError("missing article URL")
    resolved = urljoin(source_url, value)
    source = urlsplit(source_url)
    article = urlsplit(resolved)
    if (
        article.scheme != "https"
        or article.hostname != source.hostname
        or article.username is not None
        or article.password is not None
    ):
        raise ValueError("article URL must be same-origin HTTPS")
    return resolved


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in value
    )
    return " ".join(without_controls.split())


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
    "flatt_blog": fetch_flatt_blog,
    "huntr_blog": fetch_html_index,
    "lakera_blog": fetch_html_index,
    "hiddenlayer_research": fetch_html_index,
}
