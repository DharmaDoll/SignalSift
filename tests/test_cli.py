from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from signalsift.cli import _default_state_path, build_parser, main, run_dry_cycle
from signalsift.dedupe import article_key
from signalsift.fetch import FetchError
from signalsift.slack import SlackDeliveryReport
from signalsift.models import (
    NormalizedItem,
    SourceConfig,
    SourcesConfig,
    load_filter_config,
)
from signalsift.state import NotificationState, NotifiedRecord, save_state


ROOT = Path(__file__).resolve().parents[1]
FILTERS = load_filter_config(ROOT / "config/supply_chain_vulnerability.yaml")
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
SOURCE = SourceConfig(
    id="example",
    name="Example Research",
    enabled=True,
    type="rss",
    url="https://example.test/feed",
    priority=3,
)


def candidate() -> NormalizedItem:
    return NormalizedItem(
        id="entry-1",
        source_id="example",
        title="Malicious npm package steals credentials",
        url="https://example.test/article?utm_source=feed",
        published_at=NOW - timedelta(hours=2),
        summary="Affected versions and mitigation are available.",
    )


def dropped_candidate() -> NormalizedItem:
    return NormalizedItem(
        id="entry-2",
        source_id="example",
        title="General AI product announcement",
        url="https://example.test/ai-news",
        published_at=NOW - timedelta(hours=3),
        summary="A new AI assistant feature is available.",
    )


def test_review_dry_run_ignores_history_without_writing_state(tmp_path: Path) -> None:
    item = candidate()
    state_path = tmp_path / "state" / "notified.json"
    state = NotificationState(
        initial_cutoff_at=NOW - timedelta(hours=24),
        items={
            article_key(item): NotifiedRecord(
                source="example",
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                notified_at=NOW - timedelta(hours=1),
            )
        },
    )
    save_state(state_path, state)
    before = state_path.read_bytes()
    output = StringIO()

    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=state_path,
        review_lookback_hours=168,
        now=NOW,
        fetcher=lambda source: (item, dropped_candidate()),
        output=output,
    )

    assert exit_code == 0
    assert (
        "mode=review profile=supply_chain_vulnerability lookback_hours=168"
        in output.getvalue()
    )
    assert "title=Malicious npm package steals credentials" in output.getvalue()
    assert "notifications=1" in output.getvalue()
    assert "reason=global-filter source=Example Research" in output.getvalue()
    assert "title=General AI product announcement" in output.getvalue()
    assert "review_dropped=1" in output.getvalue()
    assert "state_changed=false slack_sent=false" in output.getvalue()
    assert state_path.read_bytes() == before


def test_normal_dry_run_respects_notification_history(tmp_path: Path) -> None:
    item = candidate()
    state_path = tmp_path / "notified.json"
    state = NotificationState(
        initial_cutoff_at=NOW - timedelta(hours=24),
        items={
            article_key(item): NotifiedRecord(
                "example", item.title, item.url, item.published_at, NOW - timedelta(hours=1)
            )
        },
    )
    save_state(state_path, state)
    before = state_path.read_bytes()
    output = StringIO()

    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: (item,),
        output=output,
    )

    assert exit_code == 0
    assert "duplicates=1" in output.getvalue()
    assert "notifications=0" in output.getvalue()
    assert state_path.read_bytes() == before


def test_dry_run_is_deterministic_for_fixed_clock_and_input(tmp_path: Path) -> None:
    outputs: list[str] = []
    for index in range(2):
        output = StringIO()
        exit_code = run_dry_cycle(
            SourcesConfig((SOURCE,)),
            FILTERS,
            state_path=tmp_path / f"state-{index}.json",
            now=NOW,
            fetcher=lambda source: (candidate(), dropped_candidate()),
            output=output,
        )
        assert exit_code == 0
        outputs.append(output.getvalue())

    assert outputs[0] == outputs[1]


def test_source_failure_does_not_stop_remaining_sources(tmp_path: Path) -> None:
    failed_source = SourceConfig(
        id="failed",
        name="Failed",
        enabled=True,
        type="rss",
        url="https://failed.test/feed",
        priority=1,
    )
    output = StringIO()

    def fetch(source: SourceConfig) -> tuple[NormalizedItem, ...]:
        if source.id == "failed":
            raise FetchError("simulated source failure")
        return (candidate(),)

    exit_code = run_dry_cycle(
        SourcesConfig((failed_source, SOURCE)),
        FILTERS,
        state_path=tmp_path / "missing.json",
        review_lookback_hours=168,
        now=NOW,
        fetcher=fetch,
        output=output,
    )

    assert exit_code == 1
    assert "source=failed fetch=failed" in output.getvalue()
    assert "source=example fetch=ok" in output.getvalue()
    assert "--- operational-alert-preview ---" in output.getvalue()
    assert "Failed (`failed`): FetchError: simulated source failure" in output.getvalue()
    assert "notifications=1" in output.getvalue()
    assert not (tmp_path / "missing.json").exists()


def test_live_cycle_marks_only_successful_slack_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = candidate()
    state_path = tmp_path / "notified.json"
    captured: list[tuple[str, int]] = []

    def deliver(webhook: str, batches: tuple[object, ...]) -> SlackDeliveryReport:
        captured.append((webhook, len(batches)))
        batch = batches[0]
        return SlackDeliveryReport(
            succeeded=(batch.results[0],),
            failed=(),
            failures=(),
        )

    monkeypatch.setattr("signalsift.cli.send_notification_batches", deliver)
    output = StringIO()
    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: (item,),
        output=output,
        deliver=True,
        webhook_url="https://hooks.slack.test/services/test",
    )

    assert exit_code == 0
    assert captured == [("https://hooks.slack.test/services/test", 1)]
    saved = load_state_for_test(state_path)
    assert set(saved.items) == {article_key(item)}
    assert "state_changed=true slack_sent=true" in output.getvalue()


def test_live_cycle_returns_failure_without_marking_failed_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = candidate()

    def deliver(webhook: str, batches: tuple[object, ...]) -> SlackDeliveryReport:
        batch = batches[0]
        return SlackDeliveryReport(
            succeeded=(),
            failed=(batch.results[0],),
            failures=(),
        )

    monkeypatch.setattr("signalsift.cli.send_notification_batches", deliver)
    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=tmp_path / "notified.json",
        now=NOW,
        fetcher=lambda source: (item,),
        output=StringIO(),
        deliver=True,
        webhook_url="https://hooks.slack.test/services/test",
    )

    assert exit_code == 1
    saved = load_state_for_test(tmp_path / "notified.json")
    assert saved.items == {}


def test_live_cycle_sends_source_failure_alert_and_keeps_success_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed_source = SourceConfig(
        id="failed",
        name="Failed",
        enabled=True,
        type="rss",
        url="https://failed.test/feed",
        priority=1,
    )
    operational: list[tuple[str, str]] = []

    def send_operational(webhook: str, text: str) -> None:
        operational.append((webhook, text))
        return None

    def deliver(webhook: str, batches: tuple[object, ...]) -> SlackDeliveryReport:
        batch = batches[0]
        return SlackDeliveryReport(
            succeeded=(batch.results[0],),
            failed=(),
            failures=(),
        )

    def fetch(source: SourceConfig) -> tuple[NormalizedItem, ...]:
        if source.id == "failed":
            raise FetchError("simulated source failure")
        return (candidate(),)

    monkeypatch.setattr("signalsift.cli.send_operational_alert", send_operational)
    monkeypatch.setattr("signalsift.cli.send_notification_batches", deliver)
    output = StringIO()
    exit_code = run_dry_cycle(
        SourcesConfig((failed_source, SOURCE)),
        FILTERS,
        state_path=tmp_path / "notified.json",
        now=NOW,
        fetcher=fetch,
        output=output,
        deliver=True,
        webhook_url="https://hooks.slack.test/services/test",
    )

    assert exit_code == 1
    assert len(operational) == 1
    assert operational[0][0] == "https://hooks.slack.test/services/test"
    assert "Failed (`failed`): FetchError: simulated source failure" in operational[0][1]
    saved = load_state_for_test(tmp_path / "notified.json")
    assert set(saved.items) == {article_key(candidate())}


def test_review_lookback_requires_dry_run() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--review-lookback-hours", "168"])

    assert exc_info.value.code == 2


def test_live_run_requires_profile_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FILTERS.profile.webhook_env, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--profile", "supply-chain-vulnerability"])

    assert exc_info.value.code == 2


def test_profiles_have_independent_default_state_paths() -> None:
    args = build_parser().parse_args(
        ["run", "--profile", "ai-security", "--dry-run"]
    )

    assert args.profile == "ai-security"
    assert args.state_path is None
    assert _default_state_path("supply_chain_vulnerability") == Path(
        "state/supply_chain_vulnerability.json"
    )
    assert _default_state_path("ai_security") == Path("state/ai_security.json")


def load_state_for_test(path: Path):
    from signalsift.state import load_state

    return load_state(path, now=NOW, initial_lookback_hours=24)
