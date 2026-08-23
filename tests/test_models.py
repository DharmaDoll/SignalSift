from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from signalsift.models import (
    ConfigError,
    NormalizedItem,
    load_filter_config,
    load_profile_sources_config,
    load_sources_config,
)


ROOT = Path(__file__).resolve().parents[1]


def write_yaml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_repository_configuration() -> None:
    sources, _ = load_profile_sources_config(ROOT / "config/supply_chain_sources.yaml")
    _, security = load_profile_sources_config(ROOT / "config/supply_chain_sources.yaml")
    ai_sources, ai_security = load_profile_sources_config(
        ROOT / "config/ai_security.yaml"
    )

    assert len(sources.enabled_sources) == 14
    assert len(ai_sources.enabled_sources) == 15
    assert "cisa_kev" not in {source.id for source in ai_sources.enabled_sources}
    assert {source.id for source in ai_sources.enabled_sources} >= {
        "ai_incident_database",
        "huntr",
        "lakera",
        "microsoft_ai_red_team",
        "hiddenlayer",
        "adversa_ai",
    }
    assert sources.enabled_sources[1].id == "sans_isc"
    assert sources.enabled_sources[2].adapter == "cisa_kev"
    assert sources.enabled_sources[3].adapter == "flatt_blog"
    for profile_sources in (sources, ai_sources):
        sans_isc = next(
            source
            for source in profile_sources.enabled_sources
            if source.id == "sans_isc"
        )
        assert sans_isc.type == "rss"
        assert sans_isc.priority == 2
        assert sans_isc.url == "https://isc.sans.edu/rssfeed.xml"
        assert sans_isc.source_filter is not None
        assert sans_isc.source_filter.exclude == ("ISC Stormcast",)
    github = next(
        source
        for source in sources.enabled_sources
        if source.id == "github_security_blog"
    )
    assert not github.match_content
    assert github.url == "https://github.blog/security/feed/"
    assert github.source_filter is None
    google = next(
        source
        for source in sources.enabled_sources
        if source.id == "google_threat_intel"
    )
    assert not google.match_content
    assert google.match_summary_chars == 500
    wiz_ai = next(
        source for source in ai_sources.enabled_sources if source.id == "wiz_ai"
    )
    assert wiz_ai.url == "https://www.wiz.io/feed/tag/ai/rss.xml"
    wiz_data = next(
        source
        for source in ai_sources.enabled_sources
        if source.id == "wiz_datasecurity"
    )
    assert wiz_data.url == "https://www.wiz.io/feed/tag/datasecurity/rss.xml"
    wiz_security = next(
        source for source in sources.enabled_sources if source.id == "wiz_security"
    )
    assert wiz_security.url == "https://www.wiz.io/feed/tag/security/rss.xml"
    wiz_cirt = next(
        source for source in sources.enabled_sources if source.id == "wiz_cirt"
    )
    assert wiz_cirt.url == "https://www.wiz.io/feed/tag/cirt/rss.xml"
    assert (
        next(
            source for source in sources.enabled_sources if source.id == "wiz_research"
        ).url
        == "https://www.wiz.io/feed/tag/research/rss.xml"
    )
    assert (
        next(
            source
            for source in ai_sources.enabled_sources
            if source.id == "wiz_research"
        ).url
        == "https://www.wiz.io/feed/tag/research/rss.xml"
    )
    bitwarden_ai = next(
        source for source in ai_sources.enabled_sources if source.id == "bitwarden"
    )
    assert bitwarden_ai.url == "https://bitwarden.com/blog/feed.xml"
    assert bitwarden_ai.source_filter is not None
    assert bitwarden_ai.source_filter.include_any == ("Agentic AI",)
    bitwarden_supply = next(
        source for source in sources.enabled_sources if source.id == "bitwarden"
    )
    assert bitwarden_supply.url == "https://bitwarden.com/blog/feed.xml"
    assert bitwarden_supply.source_filter is not None
    assert bitwarden_supply.source_filter.include_any == (
        "Security Tips",
        "Secure Sharing",
    )
    microsoft = next(
        source
        for source in ai_sources.enabled_sources
        if source.id == "microsoft_ai_red_team"
    )
    assert microsoft.match_content is False
    assert microsoft.match_summary_chars == 1000
    assert microsoft.source_filter is not None
    assert microsoft.source_filter.include_any == ()
    assert microsoft.source_filter.exclude == (
        "leader",
        "leadership compass",
        "what's new",
        "product announcement",
        "platform update",
        "customer story",
    )
    assert security.profile.id == "supply_chain_vulnerability"
    assert (
        security.profile.webhook_env == "SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY"
    )
    assert security.profile.force_notify_source_ids == (
        "cisa_kev",
        "wiz_security",
        "wiz_cirt",
        "stepsecurity",
        "github_security_blog",
    )
    assert ai_security.profile.id == "ai_security"
    assert ai_security.profile.webhook_env == "SLACK_WEBHOOK_URL_AI_SECURITY"
    assert ai_security.profile.force_notify_source_ids == (
        "wiz_ai",
        "wiz_datasecurity",
        "bitwarden",
    )
    assert security.notification.threshold == 7
    assert security.negative_terms.score == -5
    assert security.negative_terms.mild.score == -3
    assert dict(security.source_priority_score) == {1: 1, 2: 2, 3: 3}
    rules = {rule.name: rule for rule in security.rules}
    assert rules["supply_chain_vulnerability"].exclude_source_ids == (
        "jpcert",
        "github_advisories",
    )
    assert rules["supply_chain_vulnerability_jpcert"].source_ids == ("jpcert",)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("https://example.test/feed", "duplicate source id"),
        ("http://example.test/feed", "expected HTTPS URL"),
    ],
)
def test_rejects_duplicate_source_ids_and_http_urls(
    tmp_path: Path, replacement: str, message: str
) -> None:
    source_id = "same" if "duplicate" in message else "source"
    second_source = (
        ""
        if "duplicate" not in message
        else f"""
  - id: same
    name: Second
    enabled: true
    type: rss
    url: https://example.test/second
    priority: 1
"""
    )
    path = write_yaml(
        tmp_path,
        f"""sources:
  - id: {source_id}
    name: Example
    enabled: true
    type: rss
    url: {replacement}
    priority: 1
{second_source}""",
    )

    with pytest.raises(ConfigError, match=message):
        load_sources_config(path)


def test_rejects_unknown_source_field(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """sources:
  - id: example
    name: Example
    enabled: true
    type: rss
    url: https://example.test/feed
    priority: 1
    selector: article
""",
    )

    with pytest.raises(ConfigError, match="unknown field.*selector"):
        load_sources_config(path)


def test_rejects_unknown_adapter(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """sources:
  - id: example
    name: Example
    enabled: true
    type: json
    url: https://example.test/feed
    adapter: arbitrary_python
    priority: 1
""",
    )

    with pytest.raises(ConfigError, match="unknown adapter"):
        load_sources_config(path)


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "sources: []\nsources: []\n")

    with pytest.raises(ConfigError, match="duplicate YAML key"):
        load_sources_config(path)


def test_rejects_invalid_notification_boundary(tmp_path: Path) -> None:
    text = (ROOT / "config/supply_chain_sources.yaml").read_text(encoding="utf-8")
    path = write_yaml(tmp_path, text.replace("threshold: 7", "threshold: 0", 1))

    with pytest.raises(ConfigError, match="notification.threshold: must be >= 1"):
        load_profile_sources_config(path)


def test_rejects_non_positive_summary_match_limit(tmp_path: Path) -> None:
    text = (ROOT / "config/supply_chain_sources.yaml").read_text(encoding="utf-8")
    path = write_yaml(
        tmp_path, text.replace("match_summary_chars: 500", "match_summary_chars: 0")
    )

    with pytest.raises(ConfigError, match="match_summary_chars: must be >= 1"):
        load_profile_sources_config(path)


def test_rejects_rule_with_any_and_all_groups(tmp_path: Path) -> None:
    text = (ROOT / "config/supply_chain_sources.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "    any:\n      - CVE",
        "    any:\n      - CVE\n    all_groups:\n      - any:\n          - compromise",
        1,
    )
    path = write_yaml(tmp_path, text)

    with pytest.raises(ConfigError, match="exactly one of 'any' or 'all_groups'"):
        load_profile_sources_config(path)


def test_normalized_item_converts_naive_datetime_to_utc() -> None:
    item = NormalizedItem(
        id=None,
        source_id="example",
        title="Example",
        url=None,
        published_at=datetime(2026, 8, 12, 12, 0),
    )

    assert item.published_at == datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def test_normalized_item_converts_aware_datetime_to_utc() -> None:
    jst = timezone(timedelta(hours=9))
    item = NormalizedItem(
        id=None,
        source_id="example",
        title="Example",
        url=None,
        published_at=datetime(2026, 8, 12, 12, 0, tzinfo=jst),
    )

    assert item.published_at == datetime(2026, 8, 12, 3, 0, tzinfo=UTC)


def test_normalized_item_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title must not be empty"):
        NormalizedItem(
            id=None,
            source_id="example",
            title=" ",
            url=None,
            published_at=None,
        )


def test_raw_metadata_defaults_are_not_shared() -> None:
    first = NormalizedItem(None, "one", "First", None, None)
    second = NormalizedItem(None, "two", "Second", None, None)

    assert first.raw_metadata is not second.raw_metadata
