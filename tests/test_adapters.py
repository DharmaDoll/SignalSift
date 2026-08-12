from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from signalsift.adapters import ADAPTERS, AdapterError, fetch_source, parse_cisa_kev
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
        force_notify_new_entries=True,
    )


def test_cisa_adapter_registry_is_static_and_minimal() -> None:
    assert tuple(ADAPTERS) == ("cisa_kev",)


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
    assert "search_api_fulltext=CVE-2026-12345" in (item.url or "")
    assert item.raw_metadata == {
        "vendor_project": "Example Vendor",
        "product": "Example Gateway",
        "known_ransomware_campaign_use": "Unknown",
        "due_date": "2026-09-02",
        "notes": "https://example.test/advisory",
    }


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
