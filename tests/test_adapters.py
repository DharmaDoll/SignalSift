from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from signalsift.adapters import (
    ADAPTERS,
    AdapterError,
    fetch_source,
    parse_cisa_kev,
    parse_flatt_blog,
    parse_html_index,
)
from signalsift.models import SourceConfig


FIXTURES = Path(__file__).parent / "fixtures"


def cisa_source() -> SourceConfig:
    return SourceConfig(
        id="cisa_kev",
        name="CISA KEV",
        enabled=True,
        type="json",
        url="https://example.test/kev.json",
        priority=3,
        adapter="cisa_kev",
    )


def flatt_source() -> SourceConfig:
    return SourceConfig(
        id="flatt",
        name="GMO Flatt Security",
        enabled=True,
        type="html",
        url="https://blog.flatt.tech/",
        priority=3,
        adapter="flatt_blog",
    )


FLATT_INDEX_HTML = (FIXTURES / "flatt_index.html").read_bytes()


def test_cisa_adapter_registry_is_static_and_minimal() -> None:
    assert tuple(ADAPTERS) == ("cisa_kev", "flatt_blog", "huntr_blog", "lakera_blog", "hiddenlayer_research")


@pytest.mark.parametrize(
    ("adapter", "html", "title"),
    [
        ("huntr_blog", '<a data-page-track-value="en-us:cards-list:AI RCE" href="/inside-ai-rce">AI RCE</a>', "AI RCE"),
        ("lakera_blog", '<a href="/blog/prompt-injection"><div class="heading-style-h5-fn">Prompt Injection</div></a>', "Prompt Injection"),
        ("hiddenlayer_research", '<div fs-list-field="title">Agent Attack</div><a href="/research/agent-attack"></a>', "Agent Attack"),
    ],
)
def test_parse_html_research_index(adapter: str, html: str, title: str) -> None:
    (item,) = parse_html_index(html.encode(), source_id=adapter, source_url="https://example.test/", adapter=adapter)
    assert item.title == title
    assert item.url == f"https://example.test/{'inside-ai-rce' if adapter == 'huntr_blog' else 'blog/prompt-injection' if adapter == 'lakera_blog' else 'research/agent-attack'}"


def test_parse_cisa_kev_normalizes_security_fields() -> None:
    (item,) = parse_cisa_kev(
        (FIXTURES / "cisa_kev.json").read_bytes(), source_id="cisa_kev"
    )

    assert item.id == "CVE-2026-12345"
    assert item.external_ids == ("CVE-2026-12345",)
    assert item.title == "Example Gateway Authentication Bypass"
    assert item.published_at == datetime(2026, 8, 12, tzinfo=UTC)
    assert item.summary.startswith("The gateway contains")
    assert "Vendor: Example Vendor" in item.content
    assert "Product: Example Gateway" in item.content
    assert "Required action: Apply mitigations" in item.content
    assert item.categories == ("CISA KEV", "Known Exploited Vulnerability")
    assert "search_api_fulltext=CVE-2026-12345" in (item.url or "")
    assert item.raw_metadata == {
        "vendor_project": "Example Vendor",
        "product": "Example Gateway",
        "known_ransomware_campaign_use": "Unknown",
        "due_date": "2026-09-02",
        "notes": "https://example.test/advisory",
        "published_precision": "date",
    }


def test_parse_flatt_index_uses_only_article_card_metadata() -> None:
    first, second = parse_flatt_blog(
        FLATT_INDEX_HTML,
        source_id="flatt",
        source_url="https://blog.flatt.tech/",
    )

    assert first.id == "hatenablog://entry/14945776032061192456"
    assert first.title == "keyv software supply-chain attack"
    assert first.url == "https://blog.flatt.tech/entry/keyv_compromise"
    assert first.published_at == datetime(2026, 8, 4, tzinfo=UTC)
    assert first.summary == "Malicious npm packages stole credentials. Apply remediation…"
    assert first.categories == ("Supply Chain",)
    assert first.external_ids == ()
    assert "event" not in first.summary
    assert first.raw_metadata == {
        "source_format": "html-index",
        "published_precision": "date",
    }
    assert second.external_ids == ("CVE-2026-66066",)


def test_fetch_source_dispatches_flatt_adapter() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=FLATT_INDEX_HTML)
    )

    items = fetch_source(flatt_source(), transport=transport)

    assert len(items) == 2


@pytest.mark.parametrize(
    "content",
    [
        b"<html><body>No article cards</body></html>",
        b'<section class="archive-entry" data-uuid="bad"></section>',
        b'<section class="archive-entry" data-uuid="1"><time datetime="bad"></time></section>',
    ],
)
def test_parse_flatt_index_rejects_missing_or_invalid_schema(content: bytes) -> None:
    with pytest.raises(AdapterError):
        parse_flatt_blog(
            content,
            source_id="flatt",
            source_url="https://blog.flatt.tech/",
        )


def test_parse_flatt_index_rejects_cross_origin_article_url() -> None:
    content = FLATT_INDEX_HTML.replace(
        b'href="/entry/keyv_compromise"',
        b'href="https://attacker.example/entry/keyv_compromise"',
    )

    items = parse_flatt_blog(
        content,
        source_id="flatt",
        source_url="https://blog.flatt.tech/",
    )

    assert len(items) == 1
    assert items[0].title == "Rails CVE-2026-66066"


def test_fetch_source_dispatches_cisa_adapter() -> None:
    content = (FIXTURES / "cisa_kev.json").read_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))

    items = fetch_source(cisa_source(), transport=transport)

    assert [item.id for item in items] == ["CVE-2026-12345"]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "expected object"),
        ({}, "vulnerabilities must be a list"),
        ({"vulnerabilities": {}}, "vulnerabilities must be a list"),
        ({"vulnerabilities": [{"cveID": "not-a-cve"}]}, "no valid entries"),
    ],
)
def test_parse_cisa_kev_rejects_untrusted_schema(document: object, message: str) -> None:
    with pytest.raises(AdapterError, match=message):
        parse_cisa_kev(json.dumps(document).encode(), source_id="cisa_kev")


def test_parse_cisa_kev_skips_one_bad_entry(caplog: pytest.LogCaptureFixture) -> None:
    document = json.loads((FIXTURES / "cisa_kev.json").read_bytes())
    document["vulnerabilities"].insert(0, {"cveID": "bad"})

    items = parse_cisa_kev(json.dumps(document).encode(), source_id="cisa_kev")

    assert len(items) == 1
    assert "entry=0 skipped" in caplog.text
