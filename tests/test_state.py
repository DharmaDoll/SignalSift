from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from signalsift.models import EvaluationResult, NormalizedItem, SourceConfig
from signalsift.state import (
    NotificationState,
    NotifiedRecord,
    StateError,
    is_eligible_item,
    load_state,
    mark_notified,
    prune_state,
    save_state,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def item(published_at: datetime | None) -> NormalizedItem:
    return NormalizedItem(
        id="entry",
        source_id="example",
        title="Example",
        url="https://example.test/article",
        published_at=published_at,
    )


def test_missing_state_creates_and_preserves_initial_cutoff(tmp_path: Path) -> None:
    path = tmp_path / "state" / "notified.json"
    first = load_state(path, now=NOW, initial_lookback_hours=24)

    assert first.initial_cutoff_at == NOW - timedelta(hours=24)
    assert save_state(path, first)

    second = load_state(path, now=NOW + timedelta(days=2), initial_lookback_hours=24)
    assert second.initial_cutoff_at == first.initial_cutoff_at
    assert not save_state(path, second)


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"version": 2, "initial_cutoff_at": "2026-08-11T12:00:00Z", "items": {}}),
        json.dumps({"version": 1, "items": {}}),
        json.dumps({"version": 1, "initial_cutoff_at": "bad", "items": {}}),
    ],
)
def test_corrupt_or_unsupported_state_fails_safely(tmp_path: Path, content: str) -> None:
    path = tmp_path / "notified.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StateError):
        load_state(path, now=NOW, initial_lookback_hours=24)


def test_initial_cutoff_unknown_and_future_dates_are_enforced() -> None:
    state = NotificationState(initial_cutoff_at=NOW - timedelta(hours=24))

    assert is_eligible_item(item(NOW - timedelta(hours=24)), state, now=NOW)
    assert not is_eligible_item(item(NOW - timedelta(hours=24, seconds=1)), state, now=NOW)
    assert not is_eligible_item(item(None), state, now=NOW)
    assert not is_eligible_item(item(NOW + timedelta(hours=24, seconds=1)), state, now=NOW)


def test_cisa_date_added_uses_utc_date_boundary() -> None:
    state = NotificationState(
        initial_cutoff_at=datetime(2026, 8, 11, 18, 30, tzinfo=UTC)
    )
    cisa = SourceConfig(
        id="cisa_kev",
        name="CISA KEV",
        enabled=True,
        type="json",
        url="https://example.test/kev",
        priority=3,
        adapter="cisa_kev",
    )
    kev_item = NormalizedItem(
        "CVE-2026-12345",
        "cisa_kev",
        "Example",
        "https://example.test/cve",
        datetime(2026, 8, 11, tzinfo=UTC),
    )

    assert is_eligible_item(kev_item, state, now=NOW, source=cisa)
    older_kev_item = NormalizedItem(
        "CVE-2026-10000",
        "cisa_kev",
        "Older Example",
        "https://example.test/older-cve",
        datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert not is_eligible_item(older_kev_item, state, now=NOW, source=cisa)


def test_mark_notified_requires_article_key() -> None:
    state = NotificationState(initial_cutoff_at=NOW - timedelta(hours=24))
    without_key = EvaluationResult(item(NOW), 7, ("supply-chain",), "supply-chain")

    with pytest.raises(StateError, match="article_key"):
        mark_notified(state, without_key, notified_at=NOW)

    with_key = EvaluationResult(
        item(NOW), 7, ("supply-chain",), "supply-chain", article_key="abc"
    )
    mark_notified(state, with_key, notified_at=NOW)
    assert state.items["abc"].notified_at == NOW


def test_prune_removes_only_strictly_old_valid_records(caplog: pytest.LogCaptureFixture) -> None:
    cutoff = NOW - timedelta(days=180)
    state = NotificationState(
        initial_cutoff_at=NOW - timedelta(hours=24),
        items={
            "old": NotifiedRecord("a", "Old", None, None, cutoff - timedelta(seconds=1)),
            "boundary": NotifiedRecord("a", "Boundary", None, None, cutoff),
            "invalid": NotifiedRecord("a", "Invalid", None, None, "not-a-date"),
        },
    )

    assert prune_state(state, now=NOW, retention_days=180) == 1
    assert set(state.items) == {"boundary", "invalid"}
    assert "invalid notified_at" in caplog.text


def test_atomic_save_failure_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notified.json"
    path.write_text("existing\n", encoding="utf-8")
    state = NotificationState(initial_cutoff_at=NOW - timedelta(hours=24))

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        del source, destination
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(StateError, match="cannot save state safely"):
        save_state(path, state)
    assert path.read_text(encoding="utf-8") == "existing\n"
    assert list(tmp_path.glob(".*.tmp")) == []
