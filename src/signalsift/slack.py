from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Mapping
from urllib.parse import urlsplit

import httpx

from signalsift.models import EvaluationResult, SourceConfig, SourceRunStats


SLACK_TIMEOUT_SECONDS = 10.0
MAX_PAYLOAD_BYTES = 35_000
MAX_TITLE_CHARS = 300
MAX_SUMMARY_CHARS = 300
MAX_WHY_CHARS = 500
MAX_SOURCE_CHARS = 120
MAX_URL_CHARS = 2_000
MAX_ERROR_CHARS = 300
MENTION_PATTERN = re.compile(
    r"@(channel|here|everyone)(?![a-z0-9_])", re.IGNORECASE
)
TOPIC_LABELS = {
    "supply-chain-vulnerability": "Supply Chain / Vulnerability",
    "supply-chain": "Supply Chain",
    "vulnerability": "Vulnerability",
    "ai-security": "AI Security",
    "forced": "Security Alert",
}


class SlackError(ValueError):
    """Raised when Slack notification input cannot be handled safely."""


@dataclass(frozen=True, slots=True)
class SlackBatch:
    text: str
    results: tuple[EvaluationResult, ...]
    digest: bool


@dataclass(frozen=True, slots=True)
class SlackFailure:
    results: tuple[EvaluationResult, ...]
    error: str


@dataclass(frozen=True, slots=True)
class SlackDeliveryReport:
    succeeded: tuple[EvaluationResult, ...]
    failed: tuple[EvaluationResult, ...]
    failures: tuple[SlackFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.failed


def escape_slack_text(value: str) -> str:
    without_mentions = MENTION_PATTERN.sub(lambda match: f"@\u200b{match.group(1)}", value)
    return without_mentions.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_notification_batches(
    results: tuple[EvaluationResult, ...],
    sources: Mapping[str, SourceConfig],
    *,
    max_individual_messages: int,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> tuple[SlackBatch, ...]:
    if max_individual_messages < 1:
        raise SlackError("max_individual_messages must be positive")
    if max_payload_bytes < 1:
        raise SlackError("max_payload_bytes must be positive")
    ordered = _ordered_results(results)
    _validate_results(ordered, sources)
    if len(ordered) <= max_individual_messages:
        batches = tuple(
            SlackBatch(
                text=_format_individual(result, sources[result.item.source_id]),
                results=(result,),
                digest=False,
            )
            for result in ordered
        )
        for batch in batches:
            if len(_payload_bytes(batch.text)) > max_payload_bytes:
                raise SlackError("individual notification exceeds payload limit")
        return batches
    return _build_digest_batches(
        ordered,
        sources,
        max_payload_bytes=max_payload_bytes,
    )


def build_source_failure_alert(
    failures: tuple[SourceRunStats, ...],
    sources: Mapping[str, SourceConfig],
) -> str:
    """Build one compact operational alert for all source failures in a run."""

    if not failures:
        raise SlackError("source failure alert requires at least one failure")
    lines = ["⚠️ SignalSift source failure", ""]
    for failure in failures:
        source = sources.get(failure.source_id)
        source_name = source.name if source is not None else failure.source_id
        error = failure.error or "unknown source error"
        lines.append(
            f"- {_display_component(source_name, MAX_SOURCE_CHARS)} "
            f"(`{_display_component(failure.source_id, MAX_SOURCE_CHARS)}`): "
            f"{_display_component(error, MAX_ERROR_CHARS)}"
        )
    lines.extend(("", "Other sources continued processing. This run is marked failed."))
    text = "\n".join(lines)
    if len(_payload_bytes(text)) > MAX_PAYLOAD_BYTES:
        raise SlackError("source failure alert exceeds payload limit")
    return text


def send_operational_alert(
    webhook_url: str,
    text: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = SLACK_TIMEOUT_SECONDS,
) -> str | None:
    """Send an operational alert, returning a safe error string on failure."""

    _require_https_webhook(webhook_url)
    payload = _payload_bytes(text)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise SlackError("operational alert exceeds payload limit")
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            verify=True,
        ) as client:
            with client.stream(
                "POST",
                webhook_url,
                content=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            ) as response:
                if 200 <= response.status_code < 300:
                    return None
                return f"unexpected HTTP status: {response.status_code}"
    except httpx.HTTPError as exc:
        return f"HTTP request failed: {type(exc).__name__}"


def send_notification_batches(
    webhook_url: str,
    batches: tuple[SlackBatch, ...],
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = SLACK_TIMEOUT_SECONDS,
) -> SlackDeliveryReport:
    _require_https_webhook(webhook_url)
    succeeded: list[EvaluationResult] = []
    failed: list[EvaluationResult] = []
    failures: list[SlackFailure] = []
    with httpx.Client(
        timeout=httpx.Timeout(timeout_seconds),
        transport=transport,
        follow_redirects=False,
        verify=True,
    ) as client:
        for batch in batches:
            payload = _payload_bytes(batch.text)
            if len(payload) > MAX_PAYLOAD_BYTES:
                raise SlackError("notification exceeds payload limit")
            try:
                with client.stream(
                    "POST",
                    webhook_url,
                    content=payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ) as response:
                    if not 200 <= response.status_code < 300:
                        error = f"unexpected HTTP status: {response.status_code}"
                    else:
                        succeeded.extend(batch.results)
                        continue
            except httpx.HTTPError as exc:
                error = f"HTTP request failed: {type(exc).__name__}"
            failed.extend(batch.results)
            failures.append(SlackFailure(batch.results, error))
    return SlackDeliveryReport(tuple(succeeded), tuple(failed), tuple(failures))


def _format_individual(result: EvaluationResult, source: SourceConfig) -> str:
    item = result.item
    topic = TOPIC_LABELS.get(result.matched_topic, "Security Alert")
    title = _display_component(item.title, MAX_TITLE_CHARS)
    source_name = _display_component(source.name, MAX_SOURCE_CHARS)
    why = _display_component(" / ".join(result.why_matched), MAX_WHY_CHARS)
    published = (
        item.published_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        if item.published_at is not None
        else "Unknown"
    )
    lines = [
        f"🚨 [{topic}] {title}",
        "",
        f"Source: {source_name}",
        f"Why: {why}",
        f"Published: {published}",
    ]
    summary = _summary(item.summary or item.content)
    if summary:
        lines.extend(("", summary))
    url = _safe_display_url(item.url)
    if url:
        lines.extend(("", url))
    return "\n".join(lines)


def _build_digest_batches(
    results: tuple[EvaluationResult, ...],
    sources: Mapping[str, SourceConfig],
    *,
    max_payload_bytes: int,
) -> tuple[SlackBatch, ...]:
    header = "🚨 SignalSift digest"
    batches: list[SlackBatch] = []
    current_results: list[EvaluationResult] = []
    current_blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        block = _format_digest_item(index, result, sources[result.item.source_id])
        candidate_text = _digest_text(header, (*current_blocks, block))
        if current_blocks and len(_payload_bytes(candidate_text)) > max_payload_bytes:
            batches.append(
                SlackBatch(
                    text=_digest_text(header, tuple(current_blocks)),
                    results=tuple(current_results),
                    digest=True,
                )
            )
            current_results = []
            current_blocks = []
            candidate_text = _digest_text(header, (block,))
        if len(_payload_bytes(candidate_text)) > max_payload_bytes:
            raise SlackError("one digest item exceeds payload limit")
        current_results.append(result)
        current_blocks.append(block)
    if current_results:
        batches.append(
            SlackBatch(
                text=_digest_text(header, tuple(current_blocks)),
                results=tuple(current_results),
                digest=True,
            )
        )
    return tuple(batches)


def _format_digest_item(
    index: int,
    result: EvaluationResult,
    source: SourceConfig,
) -> str:
    topic = TOPIC_LABELS.get(result.matched_topic, "Security Alert")
    title = _display_component(result.item.title, MAX_TITLE_CHARS)
    source_name = _display_component(source.name, MAX_SOURCE_CHARS)
    primary_why = _display_component(" / ".join(result.why_matched[:3]), MAX_WHY_CHARS)
    lines = [
        f"{index}. [{topic}] {title}",
        f"Source: {source_name} | Why: {primary_why}",
    ]
    url = _safe_display_url(result.item.url)
    if url:
        lines.append(url)
    return "\n".join(lines)


def _ordered_results(results: tuple[EvaluationResult, ...]) -> tuple[EvaluationResult, ...]:
    return tuple(
        sorted(
            results,
            key=lambda result: (
                -result.score,
                -result.item.published_at.timestamp()
                if result.item.published_at is not None
                else float("inf"),
                result.article_key or "",
            ),
        )
    )


def _validate_results(
    results: tuple[EvaluationResult, ...], sources: Mapping[str, SourceConfig]
) -> None:
    for result in results:
        if result.article_key is None:
            raise SlackError("notification result has no article_key")
        if result.item.source_id not in sources:
            raise SlackError(f"source configuration not found: {result.item.source_id!r}")


def _summary(value: str) -> str:
    compact = " ".join(value.split())
    return _display_component(compact, MAX_SUMMARY_CHARS)


def _display_component(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) > limit:
        compact = compact[: limit - 1].rstrip() + "…"
    return escape_slack_text(compact)


def _safe_display_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return ""
    return _display_component(url, MAX_URL_CHARS)


def _digest_text(header: str, blocks: tuple[str, ...]) -> str:
    return f"{header}\n\n" + "\n\n".join(blocks)


def _payload_bytes(text: str) -> bytes:
    return json.dumps(
        {"text": text}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _require_https_webhook(url: str) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise SlackError("Slack webhook must be HTTPS without credentials")
