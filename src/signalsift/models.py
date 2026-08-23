from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
BUILTIN_ADAPTERS = frozenset(
    {
        "cisa_kev",
        "github_advisories",
        "flatt_blog",
        "huntr_blog",
        "lakera_blog",
        "hiddenlayer_research",
        "stepsecurity_threat_intel",
    }
)


class ConfigError(ValueError):
    """Raised when operator configuration is invalid."""


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class SourceFilterConfig:
    include_any: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    name: str
    enabled: bool
    type: str
    url: str
    priority: int
    adapter: str | None = None
    match_content: bool = True
    match_summary_chars: int | None = None
    source_filter: SourceFilterConfig | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SourcesConfig:
    sources: tuple[SourceConfig, ...]

    @property
    def enabled_sources(self) -> tuple[SourceConfig, ...]:
        return tuple(source for source in self.sources if source.enabled)


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    threshold: int
    initial_lookback_hours: int
    state_retention_days: int
    max_individual_messages_per_run: int


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    id: str
    webhook_env: str
    force_notify_source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TermScoreConfig:
    score: int
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NegativeTermsConfig:
    score: int
    terms: tuple[str, ...]
    mild: TermScoreConfig


@dataclass(frozen=True, slots=True)
class NamedRule:
    name: str
    score: int
    any: tuple[str, ...] = ()
    all_groups: tuple[tuple[str, ...], ...] = ()
    source_ids: tuple[str, ...] = ()
    exclude_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FilterConfig:
    profile: ProfileConfig
    notification: NotificationConfig
    negative_terms: NegativeTermsConfig
    rules: tuple[NamedRule, ...]
    boosts: tuple[NamedRule, ...]
    watch_terms: TermScoreConfig
    source_priority_score: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class NormalizedItem:
    id: str | None
    source_id: str
    title: str
    url: str | None
    published_at: datetime | None
    summary: str = ""
    content: str = ""
    categories: tuple[str, ...] = ()
    external_ids: tuple[str, ...] = ()
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if self.published_at is not None:
            published_at = self.published_at
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            object.__setattr__(self, "published_at", published_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    item: NormalizedItem
    score: int
    why_matched: tuple[str, ...]
    matched_topic: str
    article_key: str | None = None


@dataclass(slots=True)
class SourceRunStats:
    source_id: str
    fetch_status: str = "pending"
    fetched_count: int = 0
    candidate_count: int = 0
    matched_count: int = 0
    duplicate_count: int = 0
    notified_count: int = 0
    error: str | None = None


def load_sources_config(path: Path) -> SourcesConfig:
    root = _load_yaml(path)
    _reject_unknown(root, {"sources"}, "sources config")
    return _parse_sources_root(root)


def load_profile_sources_config(path: Path) -> tuple[SourcesConfig, "FilterConfig"]:
    """Load a profile file that owns both its filter and source definitions."""

    root = _load_yaml(path)
    sources = _parse_sources_root(root)
    filters = _parse_filter_root(root, allow_sources=True)
    return sources, filters


def _parse_sources_root(root: Mapping[str, Any]) -> SourcesConfig:
    source_rows = _require_sequence(root.get("sources"), "sources")
    sources = tuple(_parse_source(row, index) for index, row in enumerate(source_rows))
    source_ids: set[str] = set()
    duplicates: set[str] = set()
    for source in sources:
        if source.id in source_ids:
            duplicates.add(source.id)
        source_ids.add(source.id)
    if duplicates:
        raise ConfigError(f"duplicate source id(s): {', '.join(sorted(duplicates))}")
    return SourcesConfig(sources=sources)


def load_filter_config(path: Path) -> FilterConfig:
    root = _load_yaml(path)
    return _parse_filter_root(root)


def _parse_filter_root(
    root: Mapping[str, Any], *, allow_sources: bool = False
) -> FilterConfig:
    expected = {
        "profile",
        "notification",
        "negative_terms",
        "rules",
        "boosts",
        "watch_terms",
        "source_priority_score",
    }
    if allow_sources:
        expected.add("sources")
    required = {
        "profile",
        "notification",
        "negative_terms",
        "rules",
        "source_priority_score",
    }
    _validate_fields(root, allowed=expected, required=required, path="filter config")

    profile = _parse_profile(root["profile"])
    notification = _parse_notification(root["notification"])
    negative_terms = _parse_negative_terms(root["negative_terms"])
    rules = _parse_named_rules(root["rules"], "rules")
    boosts = _parse_named_rules(root["boosts"], "boosts") if "boosts" in root else ()
    watch_terms = (
        _parse_term_score(root["watch_terms"], "watch_terms", positive=True)
        if "watch_terms" in root
        else TermScoreConfig(score=0, terms=())
    )
    source_priority_score = _parse_priority_scores(root["source_priority_score"])
    return FilterConfig(
        profile=profile,
        notification=notification,
        negative_terms=negative_terms,
        rules=rules,
        boosts=boosts,
        watch_terms=watch_terms,
        source_priority_score=source_priority_score,
    )


def _parse_profile(value: Any) -> ProfileConfig:
    path = "profile"
    row = _require_mapping(value, path)
    expected = {"id", "webhook_env", "force_notify_source_ids"}
    _validate_fields(row, allowed=expected, required=expected, path=path)
    profile_id = _require_string(row["id"], f"{path}.id")
    if not SOURCE_ID_PATTERN.fullmatch(profile_id):
        raise ConfigError(f"{path}.id: must match {SOURCE_ID_PATTERN.pattern}")
    webhook_env = _require_string(row["webhook_env"], f"{path}.webhook_env")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", webhook_env):
        raise ConfigError(f"{path}.webhook_env: expected environment variable name")
    source_ids = tuple(
        _require_string(source_id, f"{path}.force_notify_source_ids[{index}]")
        for index, source_id in enumerate(
            _require_sequence(
                row["force_notify_source_ids"], f"{path}.force_notify_source_ids"
            )
        )
    )
    if len(set(source_ids)) != len(source_ids):
        raise ConfigError(f"{path}.force_notify_source_ids: duplicate source IDs")
    return ProfileConfig(profile_id, webhook_env, source_ids)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"{path}: cannot read configuration: {exc}") from exc
    try:
        loaded = yaml.load(text, Loader=UniqueKeySafeLoader)
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return _require_mapping(loaded, str(path))


def _parse_source(value: Any, index: int) -> SourceConfig:
    path = f"sources[{index}]"
    row = _require_mapping(value, path)
    allowed = {
        "id",
        "name",
        "enabled",
        "type",
        "url",
        "priority",
        "adapter",
        "match_content",
        "match_summary_chars",
        "source_filter",
        "notes",
    }
    required = {"id", "name", "enabled", "type", "url", "priority"}
    _validate_fields(row, allowed=allowed, required=required, path=path)

    source_id = _require_string(row["id"], f"{path}.id")
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ConfigError(f"{path}.id: must match {SOURCE_ID_PATTERN.pattern}")
    source_type = _require_string(row["type"], f"{path}.type")
    if source_type not in {"rss", "json", "html"}:
        raise ConfigError(f"{path}.type: must be 'rss', 'json', or 'html'")
    url = _require_https_url(row["url"], f"{path}.url")
    priority = _require_int(row["priority"], f"{path}.priority", minimum=1, maximum=3)
    enabled = _require_bool(row["enabled"], f"{path}.enabled")

    adapter = _optional_string(row.get("adapter"), f"{path}.adapter")
    if source_type in {"json", "html"} and enabled and adapter is None:
        raise ConfigError(
            f"{path}.adapter: enabled {source_type.upper()} sources require an adapter"
        )
    if adapter is not None and adapter not in BUILTIN_ADAPTERS:
        raise ConfigError(f"{path}.adapter: unknown adapter {adapter!r}")

    source_filter = None
    if "source_filter" in row:
        source_filter = _parse_source_filter(
            row["source_filter"], f"{path}.source_filter"
        )

    return SourceConfig(
        id=source_id,
        name=_require_string(row["name"], f"{path}.name"),
        enabled=enabled,
        type=source_type,
        url=url,
        priority=priority,
        adapter=adapter,
        match_content=_require_bool(
            row.get("match_content", True), f"{path}.match_content"
        ),
        match_summary_chars=(
            _require_int(
                row["match_summary_chars"],
                f"{path}.match_summary_chars",
                minimum=1,
            )
            if "match_summary_chars" in row
            else None
        ),
        source_filter=source_filter,
        notes=_optional_string(row.get("notes"), f"{path}.notes"),
    )


def _parse_source_filter(value: Any, path: str) -> SourceFilterConfig:
    row = _require_mapping(value, path)
    _reject_unknown(row, {"include_any", "exclude"}, path)
    return SourceFilterConfig(
        include_any=(
            _parse_terms(row["include_any"], f"{path}.include_any", allow_empty=True)
            if "include_any" in row
            else ()
        ),
        exclude=(
            _parse_terms(row["exclude"], f"{path}.exclude", allow_empty=True)
            if "exclude" in row
            else ()
        ),
    )


def _parse_notification(value: Any) -> NotificationConfig:
    path = "notification"
    row = _require_mapping(value, path)
    expected = {
        "threshold",
        "initial_lookback_hours",
        "state_retention_days",
        "max_individual_messages_per_run",
    }
    _validate_fields(row, allowed=expected, required=expected, path=path)
    return NotificationConfig(
        threshold=_require_int(row["threshold"], f"{path}.threshold", minimum=1),
        initial_lookback_hours=_require_int(
            row["initial_lookback_hours"], f"{path}.initial_lookback_hours", minimum=1
        ),
        state_retention_days=_require_int(
            row["state_retention_days"], f"{path}.state_retention_days", minimum=1
        ),
        max_individual_messages_per_run=_require_int(
            row["max_individual_messages_per_run"],
            f"{path}.max_individual_messages_per_run",
            minimum=1,
        ),
    )


def _parse_negative_terms(value: Any) -> NegativeTermsConfig:
    path = "negative_terms"
    row = _require_mapping(value, path)
    expected = {"score", "terms", "mild"}
    _validate_fields(row, allowed=expected, required=expected, path=path)
    score = _require_int(row["score"], f"{path}.score", maximum=-1)
    terms = _parse_terms(row["terms"], f"{path}.terms")
    mild = _parse_term_score(row["mild"], f"{path}.mild", positive=False)
    return NegativeTermsConfig(score=score, terms=terms, mild=mild)


def _parse_term_score(value: Any, path: str, *, positive: bool) -> TermScoreConfig:
    row = _require_mapping(value, path)
    expected = {"score", "terms"}
    _validate_fields(row, allowed=expected, required=expected, path=path)
    score = _require_int(
        row["score"],
        f"{path}.score",
        minimum=1 if positive else None,
        maximum=-1 if not positive else None,
    )
    return TermScoreConfig(
        score=score, terms=_parse_terms(row["terms"], f"{path}.terms")
    )


def _parse_named_rules(value: Any, path: str) -> tuple[NamedRule, ...]:
    rows = _require_mapping(value, path)
    if not rows:
        raise ConfigError(f"{path}: must not be empty")
    rules: list[NamedRule] = []
    for name, value in rows.items():
        rule_path = f"{path}.{name}"
        _require_string(name, f"{rule_path}.name")
        row = _require_mapping(value, rule_path)
        _reject_unknown(
            row,
            {"score", "any", "all_groups", "source_ids", "exclude_source_ids"},
            rule_path,
        )
        if "score" not in row:
            raise ConfigError(f"{rule_path}: missing field: score")
        has_any = "any" in row
        has_groups = "all_groups" in row
        if has_any == has_groups:
            raise ConfigError(
                f"{rule_path}: exactly one of 'any' or 'all_groups' is required"
            )
        any_terms = _parse_terms(row["any"], f"{rule_path}.any") if has_any else ()
        groups = (
            _parse_all_groups(row["all_groups"], f"{rule_path}.all_groups")
            if has_groups
            else ()
        )
        source_ids = (
            _parse_terms(row["source_ids"], f"{rule_path}.source_ids")
            if "source_ids" in row
            else ()
        )
        exclude_source_ids = (
            _parse_terms(row["exclude_source_ids"], f"{rule_path}.exclude_source_ids")
            if "exclude_source_ids" in row
            else ()
        )
        overlap = sorted(set(source_ids) & set(exclude_source_ids))
        if overlap:
            raise ConfigError(
                f"{rule_path}: source_ids and exclude_source_ids overlap: "
                + ", ".join(overlap)
            )
        rules.append(
            NamedRule(
                name=name,
                score=_require_int(row["score"], f"{rule_path}.score", minimum=1),
                any=any_terms,
                all_groups=groups,
                source_ids=source_ids,
                exclude_source_ids=exclude_source_ids,
            )
        )
    return tuple(rules)


def _parse_all_groups(value: Any, path: str) -> tuple[tuple[str, ...], ...]:
    groups = _require_sequence(value, path)
    if not groups:
        raise ConfigError(f"{path}: must not be empty")
    parsed: list[tuple[str, ...]] = []
    for index, value in enumerate(groups):
        group_path = f"{path}[{index}]"
        row = _require_mapping(value, group_path)
        _reject_unknown(row, {"any"}, group_path)
        if "any" not in row:
            raise ConfigError(f"{group_path}: missing field: any")
        parsed.append(_parse_terms(row["any"], f"{group_path}.any"))
    return tuple(parsed)


def _parse_priority_scores(value: Any) -> tuple[tuple[int, int], ...]:
    path = "source_priority_score"
    row = _require_mapping(value, path)
    normalized: dict[int, int] = {}
    for raw_priority, raw_score in row.items():
        priority = _require_int(raw_priority, f"{path}.key", minimum=1, maximum=3)
        if priority in normalized:
            raise ConfigError(f"{path}: duplicate priority {priority}")
        normalized[priority] = _require_int(raw_score, f"{path}.{priority}", minimum=1)
    if set(normalized) != {1, 2, 3}:
        raise ConfigError(f"{path}: priorities 1, 2, and 3 are required")
    return tuple(sorted(normalized.items()))


def _parse_terms(
    value: Any, path: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    values = _require_sequence(value, path)
    terms = tuple(
        _require_string(term, f"{path}[{index}]") for index, term in enumerate(values)
    )
    if not allow_empty and not terms:
        raise ConfigError(f"{path}: must not be empty")
    if len(set(terms)) != len(terms):
        raise ConfigError(f"{path}: duplicate terms are not allowed")
    return terms


def _require_mapping(value: Any, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected mapping")
    return value


def _require_sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{path}: expected list")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: expected non-empty string")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, path)


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: expected boolean")
    return value


def _require_int(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}: expected integer")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{path}: must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{path}: must be <= {maximum}")
    return value


def _require_https_url(value: Any, path: str) -> str:
    url = _require_string(value, path)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ConfigError(f"{path}: expected HTTPS URL without credentials")
    return url


def _reject_unknown(row: Mapping[Any, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(str(key) for key in row if key not in allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown field(s): {', '.join(unknown)}")


def _validate_fields(
    row: Mapping[Any, Any],
    *,
    allowed: set[str],
    required: set[str],
    path: str,
) -> None:
    _reject_unknown(row, allowed, path)
    missing = sorted(required - row.keys())
    if missing:
        raise ConfigError(f"{path}: missing field(s): {', '.join(missing)}")
