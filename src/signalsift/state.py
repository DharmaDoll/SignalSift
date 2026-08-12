from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from signalsift.models import EvaluationResult, NormalizedItem, SourceConfig


LOGGER = logging.getLogger(__name__)
STATE_VERSION = 1


class StateError(ValueError):
    """Raised when durable notification state is unsafe to use."""


@dataclass(frozen=True, slots=True)
class NotifiedRecord:
    source: str
    title: str
    url: str | None
    published_at: datetime | None
    notified_at: datetime | str


@dataclass(slots=True)
class NotificationState:
    initial_cutoff_at: datetime
    items: dict[str, NotifiedRecord] = field(default_factory=dict)
    version: int = STATE_VERSION


def load_state(
    path: Path,
    *,
    now: datetime,
    initial_lookback_hours: int,
) -> NotificationState:
    now = _as_utc(now, "now")
    if not path.exists():
        return NotificationState(
            initial_cutoff_at=now - timedelta(hours=initial_lookback_hours)
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state safely: {type(exc).__name__}") from exc
    if not isinstance(document, dict):
        raise StateError("state must be a JSON object")
    if document.get("version") != STATE_VERSION:
        raise StateError(f"unsupported state version: {document.get('version')!r}")
    initial_cutoff = _parse_required_datetime(
        document.get("initial_cutoff_at"), "initial_cutoff_at"
    )
    raw_items = document.get("items")
    if not isinstance(raw_items, dict):
        raise StateError("items must be an object")
    items = {
        _required_string(key, "article key"): _parse_record(value, key)
        for key, value in raw_items.items()
    }
    return NotificationState(initial_cutoff_at=initial_cutoff, items=items)


def is_eligible_item(
    item: NormalizedItem,
    state: NotificationState,
    *,
    now: datetime,
    source: SourceConfig | None = None,
) -> bool:
    if item.published_at is None:
        return False
    now = _as_utc(now, "now")
    published_at = item.published_at.astimezone(UTC)
    if published_at > now + timedelta(hours=24):
        return False
    if item.raw_metadata.get("published_precision") == "date":
        return published_at.date() >= state.initial_cutoff_at.astimezone(UTC).date()
    return published_at >= state.initial_cutoff_at


def mark_notified(
    state: NotificationState,
    result: EvaluationResult,
    *,
    notified_at: datetime,
) -> None:
    if result.article_key is None:
        raise StateError("evaluation result has no article_key")
    item = result.item
    state.items[result.article_key] = NotifiedRecord(
        source=item.source_id,
        title=item.title,
        url=item.url,
        published_at=item.published_at,
        notified_at=_as_utc(notified_at, "notified_at"),
    )


def prune_state(
    state: NotificationState,
    *,
    now: datetime,
    retention_days: int,
) -> int:
    cutoff = _as_utc(now, "now") - timedelta(days=retention_days)
    removed = 0
    for key, record in tuple(state.items.items()):
        notified_at = record.notified_at
        if isinstance(notified_at, str):
            LOGGER.warning("state item=%s retained: invalid notified_at", key)
            continue
        if notified_at < cutoff:
            del state.items[key]
            removed += 1
    return removed


def save_state(path: Path, state: NotificationState) -> bool:
    serialized = _serialize_state(state)
    try:
        if path.exists() and path.read_bytes() == serialized:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise StateError(f"cannot save state safely: {type(exc).__name__}") from exc
    return True


def _serialize_state(state: NotificationState) -> bytes:
    document = {
        "version": state.version,
        "initial_cutoff_at": _format_datetime(state.initial_cutoff_at),
        "items": {
            key: {
                "source": record.source,
                "title": record.title,
                "url": record.url,
                "published_at": (
                    _format_datetime(record.published_at)
                    if record.published_at is not None
                    else None
                ),
                "notified_at": (
                    _format_datetime(record.notified_at)
                    if isinstance(record.notified_at, datetime)
                    else record.notified_at
                ),
            }
            for key, record in sorted(state.items.items())
        },
    }
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _parse_record(value: Any, key: str) -> NotifiedRecord:
    if not isinstance(value, dict):
        raise StateError(f"items.{key} must be an object")
    source = _required_string(value.get("source"), f"items.{key}.source")
    title = _required_string(value.get("title"), f"items.{key}.title")
    url = value.get("url")
    if url is not None and not isinstance(url, str):
        raise StateError(f"items.{key}.url must be a string or null")
    published_value = value.get("published_at")
    published_at = (
        _parse_required_datetime(published_value, f"items.{key}.published_at")
        if published_value is not None
        else None
    )
    notified_value = value.get("notified_at")
    if not isinstance(notified_value, str) or not notified_value:
        raise StateError(f"items.{key}.notified_at must be a non-empty string")
    try:
        notified_at: datetime | str = _parse_datetime(notified_value)
    except StateError:
        notified_at = notified_value
    return NotifiedRecord(source, title, url, published_at, notified_at)


def _parse_required_datetime(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise StateError(f"{path} must be a non-empty datetime string")
    try:
        return _parse_datetime(value)
    except StateError as exc:
        raise StateError(f"{path} is not a valid timezone-aware datetime") from exc


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateError("invalid datetime") from exc
    if parsed.tzinfo is None:
        raise StateError("datetime has no timezone")
    return parsed.astimezone(UTC)


def _as_utc(value: datetime, path: str) -> datetime:
    if value.tzinfo is None:
        raise StateError(f"{path} must be timezone-aware")
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return _as_utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise StateError(f"{path} must be a non-empty string")
    return value
