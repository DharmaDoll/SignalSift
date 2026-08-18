from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import TextIOBase
from pathlib import Path

from signalsift.adapters import fetch_source
from signalsift.dedupe import article_key, deduplicate_results
from signalsift.fetch import FetchError
from signalsift.filter import evaluate_item, passes_source_filter
from signalsift.models import (
    ConfigError,
    EvaluationResult,
    FilterConfig,
    NormalizedItem,
    SourceConfig,
    SourcesConfig,
    SourceRunStats,
    load_profile_sources_config,
)
from signalsift.slack import (
    SlackDeliveryReport,
    SlackError,
    build_notification_batches,
    build_source_failure_alert,
    send_notification_batches,
    send_operational_alert,
)
from signalsift.state import (
    NotificationState,
    StateError,
    is_eligible_item,
    load_state,
    mark_observed,
    mark_notified,
    prune_state,
    save_state,
)


Fetcher = Callable[[SourceConfig], tuple[NormalizedItem, ...]]
ReviewDrop = tuple[NormalizedItem, SourceConfig, str]
PROFILE_CONFIG_PATHS = {
    "supply-chain-vulnerability": Path("config/supply_chain_sources.yaml"),
    "ai-security": Path("config/ai_security.yaml"),
}


@dataclass(frozen=True, slots=True)
class SourceProcessingResult:
    stats: SourceRunStats
    matched: tuple[EvaluationResult, ...] = ()
    review_dropped: tuple[ReviewDrop, ...] = ()
    observed_count: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalsift")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one collection cycle.")
    run_parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_CONFIG_PATHS),
        default="supply-chain-vulnerability",
        help="Filtering and delivery profile.",
    )
    mode_group = run_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run", action="store_true", help="Do not notify or write state."
    )
    mode_group.add_argument(
        "--simulate-delivery",
        action="store_true",
        help="Do not call Slack; record matched items in local state as simulated successes.",
    )
    run_parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help="Notification state file path (default: state/<profile>.json).",
    )
    run_parser.add_argument(
        "--review-lookback-hours",
        type=_positive_int,
        help="Dry-run only: re-evaluate this many hours without notification history.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "run":  # pragma: no cover - argparse enforces the command
        parser.error("unknown command")

    if args.review_lookback_hours is not None and not args.dry_run:
        parser.error("--review-lookback-hours requires --dry-run")

    try:
        sources, filters = _load_profile(args.profile)
        state_path = args.state_path or _default_state_path(filters.profile.id)
        webhook_url = _resolve_webhook_url(
            filters,
            state_path=state_path,
            dry_run=args.dry_run,
            simulate_delivery=args.simulate_delivery,
        )
        return run_dry_cycle(
            sources,
            filters,
            state_path=state_path,
            review_lookback_hours=args.review_lookback_hours,
            deliver=not args.dry_run,
            simulate_delivery=args.simulate_delivery,
            webhook_url=webhook_url,
        )
    except (ConfigError, StateError, SlackError) as exc:
        parser.exit(2, f"configuration error: {exc}\n")


def _load_profile(profile_name: str) -> tuple[SourcesConfig, FilterConfig]:
    sources, filters = load_profile_sources_config(PROFILE_CONFIG_PATHS[profile_name])
    expected_profile_id = profile_name.replace("-", "_")
    if filters.profile.id != expected_profile_id:
        raise ConfigError(
            f"profile ID mismatch: expected {expected_profile_id!r}, "
            f"got {filters.profile.id!r}"
        )

    known_source_ids = {source.id for source in sources.sources}
    unknown_force_sources = sorted(
        set(filters.profile.force_notify_source_ids) - known_source_ids
    )
    if unknown_force_sources:
        raise ConfigError(
            "profile.force_notify_source_ids: unknown source ID(s): "
            + ", ".join(unknown_force_sources)
        )
    return sources, filters


def _resolve_webhook_url(
    filters: FilterConfig,
    *,
    state_path: Path,
    dry_run: bool,
    simulate_delivery: bool,
) -> str | None:
    if simulate_delivery:
        if not _is_local_state_path(state_path):
            raise ConfigError("--simulate-delivery requires --state-path under .local/")
        return None
    if dry_run:
        return None

    webhook_url = os.environ.get(filters.profile.webhook_env)
    if not webhook_url:
        raise ConfigError(
            f"required webhook environment variable is missing: {filters.profile.webhook_env}"
        )
    return webhook_url


def _initialize_cycle(
    filters: FilterConfig,
    *,
    state_path: Path,
    current_time: datetime,
    review_lookback_hours: int | None,
    deliver: bool,
    simulate_delivery: bool,
) -> tuple[NotificationState, frozenset[str], str]:
    if review_lookback_hours is not None:
        if review_lookback_hours < 1:
            raise ConfigError("review lookback hours must be positive")
        state = NotificationState(
            initial_cutoff_at=current_time - timedelta(hours=review_lookback_hours)
        )
        mode = (
            f"review profile={filters.profile.id} "
            f"lookback_hours={review_lookback_hours}"
        )
        return state, frozenset(), mode

    state = load_state(
        state_path,
        now=current_time,
        initial_lookback_hours=filters.notification.initial_lookback_hours,
    )
    if deliver:
        run_mode = "live"
    elif simulate_delivery:
        run_mode = "simulated-delivery"
    else:
        run_mode = "dry-run"
    return state, frozenset(state.items), f"{run_mode} profile={filters.profile.id}"


def _process_source(
    source: SourceConfig,
    filters: FilterConfig,
    *,
    state: NotificationState,
    notified_keys: frozenset[str],
    seen_keys: frozenset[str],
    current_time: datetime,
    state_existed: bool,
    review: bool,
    delivery_mode: bool,
    fetcher: Fetcher,
) -> SourceProcessingResult:
    stats = SourceRunStats(source_id=source.id)
    review_dropped: list[ReviewDrop] = []
    observed_count = 0
    try:
        items = fetcher(source)
        stats.fetch_status = "ok"
        stats.fetched_count = len(items)
        candidates: list[NormalizedItem] = []
        for item in items:
            if not passes_source_filter(item, source):
                if review:
                    review_dropped.append((item, source, "source-filter"))
                continue

            key = article_key(item)
            passes_cutoff = is_eligible_item(
                item, state, now=current_time, source=source
            )
            if item.published_at is None and source.type == "html":
                if delivery_mode and not state_existed:
                    if key not in state.observed:
                        mark_observed(state, item, observed_at=current_time, key=key)
                        observed_count += 1
                    continue
                if key in state.observed or key in notified_keys:
                    continue
                passes_cutoff = True
            if passes_cutoff:
                candidates.append(item)

        stats.candidate_count = len(candidates)
        matched: list[EvaluationResult] = []
        for item in candidates:
            drop_reason: list[str] = []
            result = evaluate_item(
                item,
                source,
                filters,
                force_notify=source.id in filters.profile.force_notify_source_ids,
                drop_reason=drop_reason,
            )
            if result is None:
                if review:
                    reason = drop_reason[0] if drop_reason else "unknown"
                    review_dropped.append((item, source, f"global-filter:{reason}"))
                continue
            matched.append(result)

        stats.matched_count = len(matched)
        unique, stats.duplicate_count = deduplicate_results(
            tuple(matched), notified_keys=seen_keys
        )
        return SourceProcessingResult(
            stats=stats,
            matched=unique,
            review_dropped=tuple(review_dropped),
            observed_count=observed_count,
        )
    except FetchError as exc:
        stats.fetch_status = "failed"
        stats.error = f"{type(exc).__name__}: {exc}"
        return SourceProcessingResult(stats=stats)


def run_dry_cycle(
    sources: SourcesConfig,
    filters: FilterConfig,
    *,
    state_path: Path,
    review_lookback_hours: int | None = None,
    now: datetime | None = None,
    fetcher: Fetcher = fetch_source,
    output: TextIOBase | None = None,
    deliver: bool = False,
    simulate_delivery: bool = False,
    webhook_url: str | None = None,
) -> int:
    """Run one collection cycle, optionally delivering and persisting successes."""

    if simulate_delivery:
        deliver = False
    if (deliver or simulate_delivery) and review_lookback_hours is not None:
        raise ConfigError("delivery modes cannot use review lookback")
    if deliver and not webhook_url:
        raise ConfigError("live delivery requires a webhook URL")

    output = output or sys.stdout
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    state_existed = state_path.exists()
    state, notified_keys, mode = _initialize_cycle(
        filters,
        state_path=state_path,
        current_time=current_time,
        review_lookback_hours=review_lookback_hours,
        deliver=deliver,
        simulate_delivery=simulate_delivery,
    )

    print(
        f"mode={mode} now={_format_datetime(current_time)} "
        f"cutoff={_format_datetime(state.initial_cutoff_at)}",
        file=output,
    )
    all_results: list[EvaluationResult] = []
    review_dropped: list[ReviewDrop] = []
    seen_keys = set(notified_keys)
    stats: list[SourceRunStats] = []
    had_source_failure = False
    baseline_observed = 0
    for source in sources.enabled_sources:
        processed = _process_source(
            source,
            filters,
            state=state,
            notified_keys=notified_keys,
            seen_keys=frozenset(seen_keys),
            current_time=current_time,
            state_existed=state_existed,
            review=review_lookback_hours is not None,
            delivery_mode=deliver or simulate_delivery,
            fetcher=fetcher,
        )
        stats.append(processed.stats)
        all_results.extend(processed.matched)
        review_dropped.extend(processed.review_dropped)
        baseline_observed += processed.observed_count
        seen_keys.update(
            result.article_key
            for result in processed.matched
            if result.article_key is not None
        )
        had_source_failure |= processed.stats.fetch_status == "failed"
        _print_source_stats(processed.stats, output)

    results = tuple(all_results)
    source_map = {source.id: source for source in sources.enabled_sources}
    source_failures = tuple(stat for stat in stats if stat.fetch_status == "failed")
    delivery_failed = False
    state_changed = False
    if source_failures:
        print("\n--- operational-alert-preview ---", file=output)
        operational_text = build_source_failure_alert(source_failures, source_map)
        if deliver:
            operational_error = send_operational_alert(
                webhook_url or "", operational_text
            )
            if operational_error is not None:
                delivery_failed = True
                print(f"operational alert failed: {operational_error}", file=output)
        else:
            print(operational_text, file=output)
    batches = build_notification_batches(
        results,
        source_map,
        max_individual_messages=filters.notification.max_individual_messages_per_run,
    )
    ordered_results = tuple(result for batch in batches for result in batch.results)
    if deliver or simulate_delivery:
        if deliver:
            report = send_notification_batches(webhook_url or "", batches)
        else:
            report = SlackDeliveryReport(
                succeeded=ordered_results,
                failed=(),
                failures=(),
            )
        notification_time = current_time
        for succeeded in report.succeeded:
            mark_notified(state, succeeded, notified_at=notification_time)
        if not report.ok:
            delivery_failed = True
        for failure in report.failures:
            delivery_failed = True
            print(f"notification failed: {failure.error}", file=output)
        pruned = prune_state(
            state,
            now=current_time,
            retention_days=filters.notification.state_retention_days,
        )
        state_changed = (
            bool(report.succeeded)
            or baseline_observed > 0
            or pruned > 0
            or not state_existed
        )
        if state_changed:
            save_state(state_path, state)
        for stat in stats:
            stat.notified_count = sum(
                result.item.source_id == stat.source_id for result in report.succeeded
            )
    elif review_lookback_hours is not None:
        for index, result in enumerate(ordered_results, start=1):
            _print_review_candidate(
                index, result, source_map[result.item.source_id], output
            )
        for index, (item, source, reason) in enumerate(review_dropped, start=1):
            _print_review_dropped(index, item, source, reason, output)
    else:
        for index, batch in enumerate(batches, start=1):
            print(f"\n--- notification-preview {index}/{len(batches)} ---", file=output)
            print(batch.text, file=output)
    review_reason_counts = Counter(reason for _, _, reason in review_dropped)
    review_reason_summary = (
        ",".join(
            f"{reason}:{count}"
            for reason, count in sorted(review_reason_counts.items())
        )
        or "none"
    )
    print(
        f"summary sources={len(stats)} failures={sum(s.fetch_status == 'failed' for s in stats)} "
        f"fetched={sum(s.fetched_count for s in stats)} "
        f"candidates={sum(s.candidate_count for s in stats)} "
        f"matched={sum(s.matched_count for s in stats)} "
        f"duplicates={sum(s.duplicate_count for s in stats)} "
        f"notifications={len(results)} batches={len(batches)} "
        f"state_changed={_format_bool(state_changed)} "
        f"slack_sent={_format_bool(deliver and not delivery_failed)}",
        f"simulated_delivery={_format_bool(simulate_delivery)}",
        f"review_dropped={len(review_dropped)}",
        f"review_dropped_reasons={review_reason_summary}",
        file=output,
    )
    return 1 if had_source_failure or delivery_failed else 0


def _print_source_stats(stats: SourceRunStats, output: TextIOBase) -> None:
    line = (
        f"source={stats.source_id} fetch={stats.fetch_status} fetched={stats.fetched_count} "
        f"candidates={stats.candidate_count} matched={stats.matched_count} "
        f"duplicates={stats.duplicate_count} notified={stats.notified_count}"
    )
    if stats.error:
        line += f" error={stats.error}"
    print(line, file=output)


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _is_local_state_path(path: Path) -> bool:
    local_root = (Path.cwd() / ".local").resolve()
    resolved = path.resolve()
    return resolved == local_root or local_root in resolved.parents


def _print_review_candidate(
    index: int,
    result: EvaluationResult,
    source: SourceConfig,
    output: TextIOBase,
) -> None:
    item = result.item
    print(f"\n--- candidate {index} ---", file=output)
    print(
        f"score={result.score} topic={result.matched_topic} source={source.name}",
        file=output,
    )
    print(f"title={item.title}", file=output)
    print(
        f"published={_format_datetime(item.published_at) if item.published_at else 'Unknown'}",
        file=output,
    )
    print(f"why={' / '.join(result.why_matched)}", file=output)
    if item.url:
        print(f"url={item.url}", file=output)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _print_review_dropped(
    index: int,
    item: NormalizedItem,
    source: SourceConfig,
    reason: str,
    output: TextIOBase,
) -> None:
    print(f"\n--- dropped {index} ---", file=output)
    print(f"reason={reason} source={source.name}", file=output)
    print(f"title={item.title}", file=output)
    print(
        f"published={_format_datetime(item.published_at) if item.published_at else 'Unknown'}",
        file=output,
    )
    if item.url:
        print(f"url={item.url}", file=output)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _default_state_path(profile_id: str) -> Path:
    return Path("state") / f"{profile_id}.json"
