from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from signalsift.models import EvaluationResult, NormalizedItem, SourceConfig
from signalsift.slack import (
    SlackError,
    build_notification_batches,
    build_source_failure_alert,
    escape_slack_text,
    send_notification_batches,
    send_operational_alert,
)
from signalsift.models import SourceRunStats
from signalsift.state import NotificationState, mark_notified


SOURCE = SourceConfig(
    id="example",
    name="Example & Research @channel",
    enabled=True,
    type="rss",
    url="https://example.test/feed",
    priority=3,
)
SOURCES = {SOURCE.id: SOURCE}
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def result(
    index: int,
    *,
    score: int = 7,
    title: str | None = None,
    summary: str = "Summary",
    url: str | None = None,
    published_at: datetime | None = NOW,
) -> EvaluationResult:
    item = NormalizedItem(
        id=f"entry-{index}",
        source_id="example",
        title=title or f"Article {index}",
        url=url if url is not None else f"https://example.test/article/{index}",
        published_at=published_at,
        summary=summary,
    )
    return EvaluationResult(
        item=item,
        score=score,
        why_matched=("supply-chain", "npm", "source-priority:3"),
        matched_topic="supply-chain",
        article_key=f"key-{index:02d}",
    )


def test_escape_slack_text_blocks_markup_and_broadcast_mentions() -> None:
    escaped = escape_slack_text("A&B <tag> @channelです @HERE @everyone")

    assert escaped == "A&amp;B &lt;tag&gt; @\u200bchannelです @\u200bHERE @\u200beveryone"


def test_individual_notification_is_compact_safe_and_complete() -> None:
    candidate = result(
        1,
        title="Malicious <package> @channel",
        summary="x" * 350,
        published_at=None,
    )

    (batch,) = build_notification_batches(
        (candidate,), SOURCES, max_individual_messages=5
    )

    assert not batch.digest
    assert batch.results == (candidate,)
    assert "🚨 [Supply Chain] Malicious &lt;package&gt; @\u200bchannel" in batch.text
    assert "Source: Example &amp; Research @\u200bchannel" in batch.text
    assert "Published: Unknown" in batch.text
    assert "x" * 299 + "…" in batch.text
    assert "https://example.test/article/1" in batch.text


def test_invalid_article_url_is_omitted() -> None:
    candidate = result(1)
    unsafe_item = NormalizedItem(
        candidate.item.id,
        candidate.item.source_id,
        candidate.item.title,
        "javascript:alert(1)",
        candidate.item.published_at,
        candidate.item.summary,
    )
    unsafe = EvaluationResult(
        unsafe_item,
        candidate.score,
        candidate.why_matched,
        candidate.matched_topic,
        candidate.article_key,
    )

    (batch,) = build_notification_batches((unsafe,), SOURCES, max_individual_messages=5)

    assert "javascript:" not in batch.text


def test_six_results_switch_to_one_stably_sorted_digest() -> None:
    candidates = tuple(
        result(
            index,
            score=7 + (index % 2),
            published_at=NOW + timedelta(minutes=index),
        )
        for index in range(6)
    )

    (batch,) = build_notification_batches(
        tuple(reversed(candidates)), SOURCES, max_individual_messages=5
    )

    assert batch.digest
    assert len(batch.results) == 6
    assert [value.article_key for value in batch.results] == [
        "key-05",
        "key-03",
        "key-01",
        "key-04",
        "key-02",
        "key-00",
    ]
    assert batch.text.startswith("🚨 SignalSift digest")


def test_digest_splits_only_to_respect_payload_limit() -> None:
    candidates = tuple(
        result(index, title=f"Article {index} " + "x" * 180) for index in range(6)
    )

    batches = build_notification_batches(
        candidates,
        SOURCES,
        max_individual_messages=5,
        max_payload_bytes=900,
    )

    assert len(batches) > 1
    assert all(batch.digest for batch in batches)
    assert sum(len(batch.results) for batch in batches) == 6
    assert all(
        len(json.dumps({"text": batch.text}, ensure_ascii=False, separators=(",", ":")).encode())
        <= 900
        for batch in batches
    )


def test_delivery_continues_after_failure_and_marks_only_success() -> None:
    batches = build_notification_batches(
        (result(1, score=8), result(2, score=7)),
        SOURCES,
        max_individual_messages=5,
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["content-type"].startswith("application/json")
        assert "text" in json.loads(request.content)
        if calls == 1:
            return httpx.Response(200, content=b"ok")
        return httpx.Response(500, content=b"do-not-log-response-body")

    report = send_notification_batches(
        "https://hooks.slack.test/services/secret",
        batches,
        transport=httpx.MockTransport(handler),
    )

    assert calls == 2
    assert not report.ok
    assert [value.article_key for value in report.succeeded] == ["key-01"]
    assert [value.article_key for value in report.failed] == ["key-02"]
    assert report.failures[0].error == "unexpected HTTP status: 500"
    assert "secret" not in report.failures[0].error
    assert "do-not-log" not in report.failures[0].error

    state = NotificationState(initial_cutoff_at=NOW - timedelta(hours=24))
    for succeeded in report.succeeded:
        mark_notified(state, succeeded, notified_at=NOW)
    assert set(state.items) == {"key-01"}


def test_delivery_wraps_timeout_and_rejects_unsafe_webhook() -> None:
    batches = build_notification_batches((result(1),), SOURCES, max_individual_messages=5)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    report = send_notification_batches(
        "https://hooks.slack.test/services/secret",
        batches,
        transport=httpx.MockTransport(timeout),
    )
    assert report.failures[0].error == "HTTP request failed: ReadTimeout"

    with pytest.raises(SlackError, match="must be HTTPS"):
        send_notification_batches("http://hooks.slack.test/secret", batches)


def test_missing_article_key_is_rejected_before_delivery() -> None:
    candidate = result(1)
    missing_key = EvaluationResult(
        candidate.item,
        candidate.score,
        candidate.why_matched,
        candidate.matched_topic,
    )

    with pytest.raises(SlackError, match="article_key"):
        build_notification_batches((missing_key,), SOURCES, max_individual_messages=5)


def test_source_failures_are_compacted_and_escaped_in_one_alert() -> None:
    alert = build_source_failure_alert(
        (
            SourceRunStats(
                source_id="example",
                fetch_status="failed",
                error="AdapterError: no archive entries <script> @channel",
            ),
            SourceRunStats(
                source_id="unknown",
                fetch_status="failed",
                error="FetchError: timeout",
            ),
        ),
        SOURCES,
    )

    assert alert.startswith("⚠️ SignalSift source failure")
    assert "Example &amp; Research @\u200bchannel (`example`)" in alert
    assert "&lt;script&gt; @\u200bchannel" in alert
    assert "unknown (`unknown`)" in alert
    assert alert.count("SignalSift source failure") == 1


def test_operational_alert_delivery_returns_only_safe_errors() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert json.loads(request.content)["text"] == "alert"
        return httpx.Response(500, content=b"secret response body")

    error = send_operational_alert(
        "https://hooks.slack.test/services/secret",
        "alert",
        transport=httpx.MockTransport(handler),
    )

    assert requests == 1
    assert error == "unexpected HTTP status: 500"
    assert "secret" not in error
