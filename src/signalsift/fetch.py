from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import httpx
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from signalsift.models import NormalizedItem, SourceConfig


LOGGER = logging.getLogger(__name__)
HTTP_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
# A few feeds intermittently reject requests at the edge.  Retry only statuses
# that are commonly transient; other client errors remain visible immediately.
RETRYABLE_STATUS_CODES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})
HTTP_RETRY_ATTEMPTS = 2
HTTP_RETRY_BACKOFF_SECONDS = 0.5
EXTERNAL_ID_PATTERN = re.compile(
    r"\b(?:CVE-\d{4}-\d{4,}|GHSA-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b",
    re.IGNORECASE,
)


class FetchError(RuntimeError):
    """Raised when a configured source cannot be fetched safely."""


class FeedParseError(FetchError):
    """Raised when a feed cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class FetchedContent:
    url: str
    content: bytes
    content_type: str | None


def fetch_bytes(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    retry_attempts: int = HTTP_RETRY_ATTEMPTS,
    retry_backoff_seconds: float = HTTP_RETRY_BACKOFF_SECONDS,
) -> FetchedContent:
    """Fetch one configured URL while enforcing transport safety limits."""

    _require_https_url(url, "source URL")
    headers = {"User-Agent": _user_agent()}
    try:
        with httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            verify=True,
        ) as client:
            return _fetch_with_client(
                client,
                url,
                max_response_bytes=max_response_bytes,
                max_redirects=max_redirects,
                retry_attempts=retry_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
    except FetchError:
        raise
    except httpx.HTTPError as exc:
        raise FetchError(f"HTTP request failed: {type(exc).__name__}: {exc}") from exc


def fetch_rss(
    source: SourceConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[NormalizedItem, ...]:
    if source.type != "rss":
        raise FetchError(f"source {source.id!r} is not an RSS source")
    fetched = fetch_bytes(source.url, transport=transport)
    return parse_feed(fetched.content, source_id=source.id)


def parse_feed(content: bytes, *, source_id: str) -> tuple[NormalizedItem, ...]:
    """Parse RSS 2.0, Atom, or RSS 1.0/RDF into normalized items."""

    try:
        root = SafeElementTree.fromstring(
            content,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (DefusedXmlException, ParseError, ValueError) as exc:
        raise FeedParseError(f"unsafe or invalid XML: {type(exc).__name__}: {exc}") from exc

    root_name = _local_name(root.tag).lower()
    if root_name == "rss":
        feed_format = "rss"
        entries = tuple(element for element in root.iter() if _local_name(element.tag) == "item")
    elif root_name == "feed":
        feed_format = "atom"
        entries = tuple(element for element in root.iter() if _local_name(element.tag) == "entry")
    elif root_name == "rdf":
        feed_format = "rdf"
        entries = tuple(element for element in root.iter() if _local_name(element.tag) == "item")
    else:
        raise FeedParseError(f"unsupported feed root: {_local_name(root.tag)!r}")

    items: list[NormalizedItem] = []
    for index, entry in enumerate(entries):
        try:
            item = _normalize_entry(entry, source_id=source_id, feed_format=feed_format)
        except (TypeError, ValueError) as exc:
            LOGGER.warning("source=%s entry=%d skipped: %s", source_id, index, exc)
            continue
        if item is None:
            LOGGER.warning("source=%s entry=%d skipped: missing title", source_id, index)
            continue
        items.append(item)
    return tuple(items)


def _fetch_with_client(
    client: httpx.Client,
    url: str,
    *,
    max_response_bytes: int,
    max_redirects: int,
    retry_attempts: int,
    retry_backoff_seconds: float,
) -> FetchedContent:
    if retry_attempts < 0:
        raise ValueError("retry_attempts must be non-negative")
    if retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds must be non-negative")

    current_url = url
    for redirect_count in range(max_redirects + 1):
        redirected = False
        for attempt in range(retry_attempts + 1):
            with client.stream("GET", current_url) as response:
                if response.status_code in REDIRECT_STATUSES:
                    if redirect_count >= max_redirects:
                        raise FetchError(f"redirect limit exceeded ({max_redirects})")
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("redirect response is missing Location header")
                    next_url = str(response.url.join(location))
                    _require_https_url(next_url, "redirect URL")
                    current_url = next_url
                    redirected = True
                    break

                if not 200 <= response.status_code < 300:
                    if (
                        response.status_code in RETRYABLE_STATUS_CODES
                        and attempt < retry_attempts
                    ):
                        delay = retry_backoff_seconds * (2**attempt)
                        LOGGER.warning(
                            "retrying HTTP status %s for %s (attempt %d/%d) in %.1fs",
                            response.status_code,
                            current_url,
                            attempt + 1,
                            retry_attempts,
                            delay,
                        )
                        if delay:
                            time.sleep(delay)
                        continue
                    raise FetchError(f"unexpected HTTP status: {response.status_code}")
                _check_content_length(response, max_response_bytes)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_response_bytes:
                        raise FetchError(f"response exceeds {max_response_bytes} bytes")
                return FetchedContent(
                    url=str(response.url),
                    content=bytes(body),
                    content_type=response.headers.get("content-type"),
                )
            if redirected:
                break
        if redirected:
            continue
    raise AssertionError("redirect loop terminated unexpectedly")


def _check_content_length(response: httpx.Response, max_response_bytes: int) -> None:
    value = response.headers.get("content-length")
    if value is None:
        return
    try:
        content_length = int(value)
    except ValueError as exc:
        raise FetchError("invalid Content-Length header") from exc
    if content_length < 0:
        raise FetchError("invalid negative Content-Length header")
    if content_length > max_response_bytes:
        raise FetchError(f"response exceeds {max_response_bytes} bytes")


def _normalize_entry(
    entry: Element,
    *,
    source_id: str,
    feed_format: str,
) -> NormalizedItem | None:
    title = _plain_text(_first_child_text(entry, ("title",)))
    if not title:
        return None
    summary = _plain_text(_first_child_text(entry, ("summary", "description")))
    content = _plain_text(_first_child_text(entry, ("content", "encoded")))
    categories = _categories(entry)
    external_ids = _external_ids(" ".join((title, summary, content, *categories)))
    entry_id = _clean_optional(_first_child_text(entry, ("guid", "id")))
    id_kind = None
    if entry_id is None and feed_format == "rdf":
        entry_id = _rdf_about(entry)
        if entry_id is not None:
            id_kind = "rdf_about"
    raw_metadata = {"feed_format": feed_format}
    if id_kind is not None:
        raw_metadata["id_kind"] = id_kind
    return NormalizedItem(
        id=entry_id,
        source_id=source_id,
        title=title,
        url=_entry_url(entry),
        published_at=_entry_datetime(entry, source_id=source_id),
        summary=summary,
        content=content,
        categories=categories,
        external_ids=external_ids,
        raw_metadata=raw_metadata,
    )


def _rdf_about(entry: Element) -> str | None:
    for key, value in entry.attrib.items():
        if _local_name(key) == "about":
            return _clean_optional(value)
    return None


def _entry_url(entry: Element) -> str | None:
    fallback: str | None = None
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = _clean_optional(child.attrib.get("href"))
        rel = child.attrib.get("rel", "alternate").strip().lower()
        if href and rel in {"", "alternate"}:
            return href
        text = _clean_optional(_element_text(child))
        if text and fallback is None:
            fallback = text
    return fallback


def _entry_datetime(entry: Element, *, source_id: str) -> datetime | None:
    for name in ("published", "updated", "pubDate", "date"):
        value = _clean_optional(_first_child_text(entry, (name,)))
        if value is None:
            continue
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
        LOGGER.warning("source=%s invalid published date: %r", source_id, value)
    return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        LOGGER.debug("feed timestamp has no timezone; assuming UTC: %s", value)
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _categories(entry: Element) -> tuple[str, ...]:
    categories: list[str] = []
    for child in entry:
        if _local_name(child.tag) not in {"category", "tag", "subject"}:
            continue
        value = child.attrib.get("term") or _element_text(child)
        cleaned = _plain_text(value)
        if cleaned and cleaned not in categories:
            categories.append(cleaned)
    return tuple(categories)


def _external_ids(text: str) -> tuple[str, ...]:
    identifiers: list[str] = []
    for match in EXTERNAL_ID_PATTERN.finditer(text):
        identifier = match.group(0).upper()
        if identifier not in identifiers:
            identifiers.append(identifier)
    return tuple(identifiers)


def _first_child_text(entry: Element, names: tuple[str, ...]) -> str:
    for name in names:
        for child in entry:
            if _local_name(child.tag) == name:
                return _element_text(child)
    return ""


def _element_text(element: Element) -> str:
    return "".join(element.itertext())


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in " ".join(parser.parts)
    )
    return " ".join(without_controls.split())


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def _require_https_url(url: str, label: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or not parsed.host or parsed.userinfo:
        raise FetchError(f"{label} must be HTTPS without credentials")


def _user_agent() -> str:
    try:
        package_version = version("signalsift")
    except PackageNotFoundError:  # pragma: no cover - editable installs provide metadata
        package_version = "0"
    return f"SignalSift/{package_version}"
