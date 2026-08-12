from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from signalsift.models import ConfigError, NormalizedItem, load_filter_config, load_sources_config


ROOT = Path(__file__).resolve().parents[1]


def write_yaml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_repository_configuration() -> None:
    sources = load_sources_config(ROOT / "config/sources.yaml")
    filters = load_filter_config(ROOT / "config/filters.yaml")

    assert len(sources.enabled_sources) == 7
    assert sources.enabled_sources[1].adapter == "cisa_kev"
    assert filters.notification.threshold == 7
    assert filters.negative_terms.score == -5
    assert filters.negative_terms.mild.score == -3
    assert dict(filters.source_priority_score) == {1: 1, 2: 2, 3: 3}


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
    second_source = "" if "duplicate" not in message else f"""
  - id: same
    name: Second
    enabled: true
    type: rss
    url: https://example.test/second
    priority: 1
"""
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
    text = (ROOT / "config/filters.yaml").read_text(encoding="utf-8")
    path = write_yaml(tmp_path, text.replace("threshold: 7", "threshold: 0", 1))

    with pytest.raises(ConfigError, match="notification.threshold: must be >= 1"):
        load_filter_config(path)


def test_rejects_rule_with_any_and_all_groups(tmp_path: Path) -> None:
    text = (ROOT / "config/filters.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "    any:\n      - supply chain attack",
        "    any:\n      - supply chain attack\n    all_groups:\n      - any:\n          - compromise",
        1,
    )
    path = write_yaml(tmp_path, text)

    with pytest.raises(ConfigError, match="exactly one of 'any' or 'all_groups'"):
        load_filter_config(path)


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
