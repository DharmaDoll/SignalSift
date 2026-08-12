from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from signalsift.filter import evaluate_item, item_match_text, passes_source_filter, term_matches
from signalsift.models import NormalizedItem, SourceConfig, load_filter_config, load_sources_config


ROOT = Path(__file__).resolve().parents[1]
SECURITY = load_filter_config(ROOT / "config/supply_chain_vulnerability.yaml")
AI_SECURITY = load_filter_config(ROOT / "config/ai_security.yaml")
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


def test_source_filters_remove_only_publication_specific_noise() -> None:
    assert not passes_source_filter(
        item("flatt", "社員インタビュー: npm maintainer"), SOURCES["flatt"]
    )
    assert not passes_source_filter(
        item("wiz", "Supply chain webinar about a malicious package"), SOURCES["wiz"]
    )
    assert not passes_source_filter(
        item("stepsecurity", "Customer story: securing npm"), SOURCES["stepsecurity"]
    )
    assert not passes_source_filter(
        item("aikido", "Company update: malicious package research"), SOURCES["aikido"]
    )
    assert passes_source_filter(
        item("flatt", "npmパッケージ侵害の対応指針"), SOURCES["flatt"]
    )
    assert not passes_source_filter(
        item("stepsecurity", "2026 Mid-Year Update: Our Biggest Year Yet"),
        SOURCES["stepsecurity"],
    )
    assert not passes_source_filter(
        item(
            "aikido",
            "Top Acunetix alternatives",
            "Category: DevSec Tools & Comparisons",
        ),
        SOURCES["aikido"],
    )
    assert passes_source_filter(
        item("stepsecurity", "ChainDrop npm worm"), SOURCES["stepsecurity"]
    )


def test_github_security_blog_ignores_full_content_for_matching() -> None:
    content_only = NormalizedItem(
        id="github-1",
        source_id="github_security_blog",
        title="Maintainer workflow improvements",
        url="https://github.blog/security/example",
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        summary="A process update for maintainers.",
        content="Long article footer mentions npm vulnerability and CVE-2026-12345.",
    )
    summary_match = NormalizedItem(
        id="github-2",
        source_id="github_security_blog",
        title="Supply chain update",
        url="https://github.blog/security/example-2",
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        summary="GitHub disrupted supply chain attacks on npm.",
        content="",
    )

    assert (
        evaluate_item(
            content_only,
            SOURCES["github_security_blog"],
            SECURITY,
        )
        is None
    )
    result = evaluate_item(
        summary_match,
        SOURCES["github_security_blog"],
        SECURITY,
    )
    assert result is not None
    assert result.why_matched == (
        "supply-chain-vulnerability",
        "supply-chain",
        "source-priority:3",
    )


def test_google_threat_intelligence_matches_only_summary_lead() -> None:
    source = SOURCES["google_threat_intel"]
    late_noise = item(
        source.id,
        "Updated Cyber Threat Actor Naming System",
        "A taxonomy update for threat actor names. " + ("x" * 600) + " Hex package",
    )
    relevant_lead = item(
        source.id,
        "Batten Down Your Packages",
        "Mitigation guidance for software supply chain compromise. " + ("x" * 600),
    )

    assert source.match_summary_chars == 500
    assert evaluate_item(late_noise, source, SECURITY) is None
    assert evaluate_item(relevant_lead, source, SECURITY) is not None


def test_security_profile_selects_short_npm_or_pypi_context() -> None:
    npm = evaluate_item(item("flatt", "npm ecosystem incident"), SOURCES["flatt"], SECURITY)
    pypi = evaluate_item(item("aikido", "PyPI package report"), SOURCES["aikido"], SECURITY)

    assert npm is not None
    assert npm.score == 8
    assert npm.matched_topic == "supply-chain-vulnerability"
    assert pypi is not None
    assert pypi.score == 7


def test_security_profile_selects_package_ecosystems_and_requested_terms() -> None:
    terms = (
        "compromise",
        "malicious",
        "typosquatting",
        "dependency",
        "crates.io",
        "yarn",
        "pnpm",
        "pip",
        "conda",
        "Poetry",
        "Maven",
        "Maven Central",
        "Gradle",
        "NuGet",
        "RubyGems",
        "Bundler",
        "Composer",
        "Packagist",
        "Go modules",
        "Cargo",
        "Hex",
        "pub.dev",
        "CPAN",
        "CocoaPods",
        "SwiftPM",
        "Swift Package Manager",
        "LuaRocks",
        "Hackage",
        "Cabal",
        "opam",
        "Conan",
        "vcpkg",
        "0-day",
        "悪用",
        "ゼロデイ",
        "認証回避",
        "認証不要",
        "リモートコード実行",
        "bypass",
        "バイパス",
    )

    for term in terms:
        result = evaluate_item(
            item("flatt", f"Security report: {term}"), SOURCES["flatt"], SECURITY
        )
        assert result is not None, term


def test_flatt_index_excerpt_is_selected_without_full_article_noise() -> None:
    candidate = item(
        "flatt",
        "keyv 等 複数著名パッケージへのソフトウェアサプライチェーン攻撃の概要と対応指針",
        "複数の npm パッケージに悪性コードが注入されました。",
    )

    result = evaluate_item(candidate, SOURCES["flatt"], SECURITY)

    assert result is not None
    assert result.score == 8
    assert result.matched_topic == "supply-chain-vulnerability"
    assert result.why_matched == (
        "supply-chain-vulnerability",
        "npm",
        "source-priority:3",
    )


def test_security_profile_selects_ordinary_cve_for_recall() -> None:
    result = evaluate_item(
        item("wiz", "CVE-2026-10000 affects Example Server"),
        SOURCES["wiz"],
        SECURITY,
    )

    assert result is not None
    assert result.score == 8
    assert result.why_matched == (
        "supply-chain-vulnerability",
        "cve",
        "source-priority:3",
    )


def test_jpcert_uses_narrow_rule_without_broad_cve_terms() -> None:
    ordinary = evaluate_item(
        item("jpcert", "Weekly Report: Microsoft Edgeに複数の脆弱性"),
        SOURCES["jpcert"],
        SECURITY,
    )
    strong = evaluate_item(
        item("jpcert", "Weekly Report: Ruby on RailsにRCEにつながる脆弱性"),
        SOURCES["jpcert"],
        SECURITY,
    )
    other_source = evaluate_item(
        item("wiz", "CVE-2026-10000 affects Example Server"),
        SOURCES["wiz"],
        SECURITY,
    )

    assert ordinary is None
    assert strong is not None
    assert strong.matched_topic == "supply-chain-vulnerability-jpcert"
    assert other_source is not None


def test_security_profile_accepts_cve_and_vulnerability_plural_forms() -> None:
    cves = evaluate_item(
        item("aikido", "Benchmarking known CVEs"), SOURCES["aikido"], SECURITY
    )
    vulnerabilities = evaluate_item(
        item("aikido", "Eight high-severity vulnerabilities in NodeBB"),
        SOURCES["aikido"],
        SECURITY,
    )

    assert cves is not None
    assert "cves" in cves.why_matched
    assert vulnerabilities is not None
    assert "vulnerabilities" in vulnerabilities.why_matched


def test_security_marketing_penalty_still_drops_article() -> None:
    result = evaluate_item(
        item("flatt", "Supply chain webinar"), SOURCES["flatt"], SECURITY
    )

    assert result is None


def test_ai_security_requires_ai_and_security_context() -> None:
    result = evaluate_item(
        item("wiz", "MCP authorization bypass vulnerability"),
        SOURCES["wiz"],
        AI_SECURITY,
    )

    assert result is not None
    assert result.matched_topic == "ai-security"
    assert result.score == 8

    assert (
        evaluate_item(
            item("aikido", "What is AI harness engineering?"),
            SOURCES["aikido"],
            AI_SECURITY,
        )
        is None
    )


def test_ai_profile_rejects_ai_as_research_method_and_bare_agent() -> None:
    metabase = evaluate_item(
        item(
            "wiz",
            "Inside the Metabase SQLi: Exploited in the Wild",
            "Reverse engineering CVE-2026-72898 with AI to accelerate defense.",
        ),
        SOURCES["wiz"],
        AI_SECURITY,
    )
    teamcity = evaluate_item(
        item(
            "cisa_kev",
            "JetBrains TeamCity vulnerability",
            "An attacker may compromise a TeamCity build agent.",
        ),
        SOURCES["cisa_kev"],
        AI_SECURITY,
    )

    assert metabase is None
    assert teamcity is None


def test_ai_profile_selects_exposed_mcp_command_execution() -> None:
    result = evaluate_item(
        item(
            "wiz",
            "The risk hiding behind exposed MCP servers",
            "Unauthenticated Model Context Protocol servers allow command execution.",
        ),
        SOURCES["wiz"],
        AI_SECURITY,
    )

    assert result is not None
    assert result.why_matched == (
        "ai-security",
        "mcp",
        "unauthenticated",
        "source-priority:3",
    )


def test_ai_profile_selects_ai_models_researching_cves() -> None:
    result = evaluate_item(
        item("aikido", "Benchmarking 13 AI models on rediscovering known CVEs"),
        SOURCES["aikido"],
        AI_SECURITY,
    )

    assert result is not None
    assert "ai-models" in result.why_matched
    assert "cves" in result.why_matched
    assert (
        evaluate_item(
            item("wiz", "Critical authentication bypass vulnerability"),
            SOURCES["wiz"],
            AI_SECURITY,
        )
        is None
    )


def test_ai_agents_attacking_real_organizations_is_selected() -> None:
    result = evaluate_item(
        item(
            "aikido",
            "Who was behind the attack? Possibly nobody",
            "AI agents attacking real organizations with no human intent.",
        ),
        SOURCES["aikido"],
        AI_SECURITY,
    )

    assert result is not None
    assert result.score == 7
    assert result.why_matched == (
        "ai-security",
        "ai-agents",
        "attack",
        "source-priority:2",
    )


def test_skills_exploit_is_selected_by_ai_profile() -> None:
    result = evaluate_item(
        item("aikido", "Skills exploit enables credential theft"),
        SOURCES["aikido"],
        AI_SECURITY,
    )

    assert result is not None
    assert result.score == 7
    assert "skills" in result.why_matched


def test_force_notify_is_selected_by_profile_not_source_model() -> None:
    candidate = item("cisa_kev", "New catalog entry")

    assert evaluate_item(candidate, SOURCES["cisa_kev"], SECURITY) is None
    result = evaluate_item(
        candidate,
        SOURCES["cisa_kev"],
        SECURITY,
        force_notify="cisa_kev" in SECURITY.profile.force_notify_source_ids,
    )

    assert result is not None
    assert result.matched_topic == "forced"
    assert result.why_matched[-1] == "force-notify:cisa_kev"
    assert AI_SECURITY.profile.force_notify_source_ids == ()


def test_cisa_kev_category_explains_urgency() -> None:
    kev_item = NormalizedItem(
        id="CVE-2026-12345",
        source_id="cisa_kev",
        title="Example Command Injection Vulnerability",
        url="https://example.test/cve",
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
        categories=("CISA KEV", "Known Exploited Vulnerability"),
        external_ids=("CVE-2026-12345",),
    )

    result = evaluate_item(
        kev_item, SOURCES["cisa_kev"], SECURITY, force_notify=True
    )

    assert result is not None
    assert result.matched_topic == "supply-chain-vulnerability"
    assert result.score == 8
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
