from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from signalsift.fetch import FeedParseError, FetchError, fetch_bytes, parse_feed


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fetch_bytes_returns_content_and_user_agent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("SignalSift/")
        return httpx.Response(200, headers={"Content-Type": "application/xml"}, content=b"feed")

    fetched = fetch_bytes("https://example.test/feed", transport=httpx.MockTransport(handler))

    assert fetched.content == b"feed"
    assert fetched.content_type == "application/xml"
    assert fetched.url == "https://example.test/feed"


def test_fetch_bytes_follows_relative_https_redirect() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/feed":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, content=b"ok")

    fetched = fetch_bytes("https://example.test/feed", transport=httpx.MockTransport(handler))

    assert fetched.url == "https://example.test/final"
    assert seen == ["https://example.test/feed", "https://example.test/final"]


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (lambda request: httpx.Response(503, request=request), "unexpected HTTP status: 503"),
        (
            lambda request: httpx.Response(
                302, headers={"Location": "http://example.test/plain"}, request=request
            ),
            "redirect URL must be HTTPS",
        ),
        (
            lambda request: httpx.Response(
                200, headers={"Content-Length": "6"}, request=request
            ),
            "response exceeds 5 bytes",
        ),
    ],
)
def test_fetch_bytes_rejects_unsafe_responses(handler: object, message: str) -> None:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]

    with pytest.raises(FetchError, match=message):
        fetch_bytes(
            "https://example.test/feed",
            transport=transport,
            max_response_bytes=5,
        )


def test_fetch_bytes_rejects_stream_over_limit() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"123456"))

    with pytest.raises(FetchError, match="response exceeds 5 bytes"):
        fetch_bytes(
            "https://example.test/feed",
            transport=transport,
            max_response_bytes=5,
        )


def test_fetch_bytes_enforces_redirect_limit() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "/again"})
    )

    with pytest.raises(FetchError, match=r"redirect limit exceeded \(3\)"):
        fetch_bytes("https://example.test/feed", transport=transport)


def test_fetch_bytes_wraps_timeout_without_leaking_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FetchError, match="ReadTimeout"):
        fetch_bytes("https://example.test/feed", transport=httpx.MockTransport(handler))


def test_parse_rss_normalizes_and_sanitizes_content(caplog: pytest.LogCaptureFixture) -> None:
    items = parse_feed(fixture_bytes("rss.xml"), source_id="rss_source")

    assert len(items) == 1
    item = items[0]
    assert item.id == "rss-1"
    assert item.title == "Malicious npm package & CVE-2026-12345"
    assert item.published_at == datetime(2026, 8, 12, 3, 34, 56, tzinfo=UTC)
    assert item.summary == "Affected versions are listed."
    assert item.content == "Use the mitigation."
    assert item.categories == ("npm", "Supply Chain")
    assert item.external_ids == ("CVE-2026-12345",)
    assert item.raw_metadata == {"feed_format": "rss"}
    assert "missing title" in caplog.text


def test_parse_atom_prefers_alternate_link_and_published_date() -> None:
    (item,) = parse_feed(fixture_bytes("atom.xml"), source_id="atom_source")

    assert item.id == "atom-1"
    assert item.url == "https://example.test/atom-1"
    assert item.published_at == datetime(2026, 8, 12, 1, 2, 3, tzinfo=UTC)
    assert item.summary == "Prompt injection attack."
    assert item.content == "Mitigation available."
    assert item.categories == ("MCP",)
    assert item.external_ids == ("GHSA-ABCD-1234-EFGH",)


def test_parse_rdf_uses_url_fallback_and_dc_fields() -> None:
    (item,) = parse_feed(fixture_bytes("rdf.xml"), source_id="jpcert")

    assert item.id == "https://example.test/rdf-1"
    assert item.url == "https://example.test/rdf-1"
    assert item.published_at == datetime(2026, 8, 11, 15, 0, tzinfo=UTC)
    assert item.categories == ("注意喚起",)
    assert item.raw_metadata == {"feed_format": "rdf", "id_kind": "rdf_about"}


@pytest.mark.parametrize("name", ["unsafe_entity.xml"])
def test_parse_feed_rejects_unsafe_xml(name: str) -> None:
    with pytest.raises(FeedParseError, match="unsafe or invalid XML"):
        parse_feed(fixture_bytes(name), source_id="unsafe")


def test_parse_feed_rejects_malformed_or_unsupported_xml() -> None:
    with pytest.raises(FeedParseError, match="unsafe or invalid XML"):
        parse_feed(b"<rss><broken>", source_id="broken")
    with pytest.raises(FeedParseError, match="unsupported feed root"):
        parse_feed(b"<html />", source_id="html")
