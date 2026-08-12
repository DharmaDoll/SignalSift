from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from signalsift.filter import evaluate_item, item_match_text, passes_source_filter, term_matches
from signalsift.models import NormalizedItem, SourceConfig, load_filter_config, load_sources_config


ROOT = Path(__file__).resolve().parents[1]
FILTERS = load_filter_config(ROOT / "config/filters.yaml")
SOURCES = {
    source.id: source for source in load_sources_config(ROOT / "config/sources.yaml").sources
}


def item(source_id: str, title: str, summary: str = "") -> NormalizedItem:
    return NormalizedItem(
        id="entry-1",
        source_id=source_id,
        title=title,
        url="https://example.test/article",
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        summary=summary,
    )


def test_term_matching_uses_nfkc_casefold_boundaries_and_cve_prefix() -> None:
    text = item_match_text(item("jpcert", "ＰＲＥＶＥＮＴ CVE-2026-12345 ＮＰＭ"))

    assert not term_matches(text, "event")
    assert term_matches(text, "CVE-")
    assert term_matches(text, "npm")


def test_source_filter_exclude_wins_and_include_any_is_required() -> None:
    assert not passes_source_filter(
        item("wiz", "Supply chain webinar about a malicious package"), SOURCES["wiz"]
    )
    assert passes_source_filter(
        item("stepsecurity", "ChainDrop npm Worm"), SOURCES["stepsecurity"]
    )
    assert not passes_source_filter(
        item("stepsecurity", "Quarterly engineering update"), SOURCES["stepsecurity"]
    )
    assert not passes_source_filter(
        item("aikido", "Company update: malicious package research"), SOURCES["aikido"]
    )


def test_chaindrop_npm_worm_is_selected_as_supply_chain() -> None:
    candidate = item(
        "stepsecurity",
        "ChainDrop npm Worm: CI/CD credential harvester",
        "444 packages and 2,212 versions poisoned. Affected package list, IOCs, and remediation.",
    )

    result = evaluate_item(candidate, SOURCES["stepsecurity"], FILTERS)

    assert result is not None
    assert result.score == 12
    assert result.matched_topic == "supply-chain"
    assert result.why_matched == (
        "supply-chain",
        "npm-worm",
        "actionable",
        "npm",
        "source-priority:3",
    )


def test_exploited_wiz_vulnerability_is_selected() -> None:
    candidate = item(
        "wiz",
        "Inside the Metabase SQLi: Exploited in the Wild",
        "Reverse engineering Metabase CVE-2026-72898 to accelerate defense.",
    )

    result = evaluate_item(candidate, SOURCES["wiz"], FILTERS)

    assert result is not None
    assert result.score == 10
    assert result.matched_topic == "vulnerability"
    assert result.why_matched == (
        "vulnerability",
        "cve-",
        "exploited-in-the-wild",
        "active-exploitation",
        "source-priority:3",
    )


def test_generic_ai_and_routine_update_are_dropped() -> None:
    assert (
        evaluate_item(
            item("aikido", "What is AI harness engineering?", "Build a better AI agent."),
            SOURCES["aikido"],
            FILTERS,
        )
        is None
    )
    assert (
        evaluate_item(
            item("jpcert", "2026年8月マイクロソフトセキュリティ更新プログラム"),
            SOURCES["jpcert"],
            FILTERS,
        )
        is None
    )


def test_marketing_supply_chain_article_and_ordinary_cve_are_dropped() -> None:
    assert (
        evaluate_item(
            item("flatt", "Supply chain attack webinar"), SOURCES["flatt"], FILTERS
        )
        is None
    )
    assert (
        evaluate_item(
            item("wiz", "CVE-2026-10000 affects Example Server"), SOURCES["wiz"], FILTERS
        )
        is None
    )


def test_mcp_vulnerability_requires_both_contexts() -> None:
    result = evaluate_item(
        item("wiz", "MCP authorization bypass vulnerability"), SOURCES["wiz"], FILTERS
    )

    assert result is not None
    assert result.matched_topic == "ai-security"
    assert result.score >= FILTERS.notification.threshold


def test_strong_negative_takes_precedence_over_mild_negative() -> None:
    result = evaluate_item(
        item(
            "flatt",
            "Supply chain attack exploited in the wild npm event release notes",
        ),
        SOURCES["flatt"],
        FILTERS,
    )

    assert result is not None
    assert "negative:event:-5" in result.why_matched
    assert all("release-notes" not in reason for reason in result.why_matched)


def test_force_notify_only_applies_to_configured_source() -> None:
    kev_item = item("cisa_kev", "CVE-2026-12345 added to catalog")

    assert evaluate_item(kev_item, SOURCES["cisa_kev"], FILTERS) is None
    result = evaluate_item(
        kev_item, SOURCES["cisa_kev"], FILTERS, force_notify=True
    )

    assert result is not None
    assert result.matched_topic == "forced"
    assert result.why_matched[-1] == "force-notify:cisa_kev"


def test_source_mismatch_is_rejected() -> None:
    mismatched = SourceConfig(
        id="other",
        name="Other",
        enabled=True,
        type="rss",
        url="https://example.test/feed",
        priority=1,
    )

    try:
        passes_source_filter(item("jpcert", "Example"), mismatched)
    except ValueError as exc:
        assert "source_id" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("source mismatch was accepted")
