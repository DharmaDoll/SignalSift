from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from signalsift.cli import _default_state_path, build_parser, main, run_dry_cycle
from signalsift.dedupe import article_key
from signalsift.fetch import FetchError
from signalsift.slack import SlackDeliveryReport, SlackFailure
from signalsift.models import (
    NormalizedItem,
    SourceConfig,
    SourcesConfig,
    load_filter_config,
    load_profile_sources_config,
)
from signalsift.state import NotificationState, NotifiedRecord, save_state


ROOT = Path(__file__).resolve().parents[1]
_, FILTERS = load_profile_sources_config(ROOT / "config/supply_chain_sources.yaml")
AI_SOURCES, AI_FILTERS = load_profile_sources_config(ROOT / "config/ai_security.yaml")
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


def test_review_dry_run_handles_undated_html_items(tmp_path: Path) -> None:
    html_source = SourceConfig(
        id="example",
        name="Example Research",
        enabled=True,
        type="html",
        url="https://example.test/security",
        priority=3,
    )
    item = NormalizedItem(
        id="undated-entry",
        source_id="example",
        title="Malicious npm package steals credentials",
        url="https://example.test/undated",
        published_at=None,
        summary="Affected versions and mitigation are available.",
    )

    exit_code = run_dry_cycle(
        SourcesConfig((html_source,)),
        FILTERS,
        state_path=tmp_path / "missing.json",
        review_lookback_hours=168,
        now=NOW,
        fetcher=lambda source: (item,),
        output=StringIO(),
    )

    assert exit_code == 0
    assert not (tmp_path / "missing.json").exists()


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


def test_simulated_delivery_writes_state_without_calling_slack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_delivery(*args: object, **kwargs: object) -> SlackDeliveryReport:
        raise AssertionError("Slack must not be called")

    monkeypatch.setattr("signalsift.cli.send_notification_batches", unexpected_delivery)
    items = tuple(
        replace(
            candidate(),
            id=f"entry-{index}",
            url=f"https://example.test/article-{index}",
        )
        for index in range(1, 4)
    )
    state_path = tmp_path / "notified.json"
    output = StringIO()

    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: items,
        output=output,
        simulate_delivery=True,
    )

    assert exit_code == 0
    assert set(load_state_for_test(state_path).items) == {
        article_key(item) for item in items
    }
    assert "mode=simulated-delivery" in output.getvalue()
    assert "matched=3 duplicates=0 notifications=3" in output.getvalue()
    assert "state_changed=true" in output.getvalue()
    assert "slack_sent=false simulated_delivery=true" in output.getvalue()
    state_after_first_run = state_path.read_bytes()

    second_output = StringIO()
    second_exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: items,
        output=second_output,
        simulate_delivery=True,
    )

    assert second_exit_code == 0
    assert "matched=3 duplicates=3" in second_output.getvalue()
    assert "notifications=0" in second_output.getvalue()
    assert "state_changed=false" in second_output.getvalue()
    assert state_path.read_bytes() == state_after_first_run


def test_ai_security_profile_filters_and_deduplicates_simulated_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_delivery(*args: object, **kwargs: object) -> SlackDeliveryReport:
        raise AssertionError("Slack must not be called")

    monkeypatch.setattr("signalsift.cli.send_notification_batches", unexpected_delivery)
    wiz = next(source for source in AI_SOURCES.enabled_sources if source.id == "wiz")
    relevant = NormalizedItem(
        id="ai-security-1",
        source_id="wiz",
        title="MCP authorization bypass vulnerability enables credential theft",
        url="https://example.test/mcp-authorization-bypass",
        published_at=NOW - timedelta(hours=2),
        summary="Affected AI agents should rotate credentials and apply the mitigation.",
    )
    generic_ai_news = NormalizedItem(
        id="ai-news-1",
        source_id="wiz",
        title="New AI agent product announcement",
        url="https://example.test/ai-product",
        published_at=NOW - timedelta(hours=1),
        summary="A coding assistant feature is now generally available.",
    )
    state_path = tmp_path / "ai_security.json"
    first_output = StringIO()

    first_exit_code = run_dry_cycle(
        SourcesConfig((wiz,)),
        AI_FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: (relevant, generic_ai_news),
        output=first_output,
        simulate_delivery=True,
    )

    assert first_exit_code == 0
    assert set(load_state_for_test(state_path).items) == {article_key(relevant)}
    assert "mode=simulated-delivery profile=ai_security" in first_output.getvalue()
    assert "candidates=2 matched=1 duplicates=0 notifications=1" in first_output.getvalue()
    state_after_first_run = state_path.read_bytes()

    second_output = StringIO()
    second_exit_code = run_dry_cycle(
        SourcesConfig((wiz,)),
        AI_FILTERS,
        state_path=state_path,
        now=NOW,
        fetcher=lambda source: (relevant, generic_ai_news),
        output=second_output,
        simulate_delivery=True,
    )

    assert second_exit_code == 0
    assert "matched=1 duplicates=1 notifications=0" in second_output.getvalue()
    assert "state_changed=false" in second_output.getvalue()
    assert state_path.read_bytes() == state_after_first_run


def test_live_cycle_returns_failure_without_marking_failed_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = candidate()

    def deliver(webhook: str, batches: tuple[object, ...]) -> SlackDeliveryReport:
        results = tuple(result for batch in batches for result in batch.results)
        return SlackDeliveryReport(
            succeeded=(),
            failed=results,
            failures=(
                SlackFailure(results, "unexpected HTTP status: 404"),
            ),
        )

    monkeypatch.setattr("signalsift.cli.send_notification_batches", deliver)
    output = StringIO()
    exit_code = run_dry_cycle(
        SourcesConfig((SOURCE,)),
        FILTERS,
        state_path=tmp_path / "notified.json",
        now=NOW,
        fetcher=lambda source: (item,),
        output=output,
        deliver=True,
        webhook_url="https://hooks.slack.test/services/test",
    )

    assert exit_code == 1
    saved = load_state_for_test(tmp_path / "notified.json")
    assert saved.items == {}
    assert "notification failed: unexpected HTTP status: 404" in output.getvalue()
    assert "state_changed=true slack_sent=false" in output.getvalue()


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
