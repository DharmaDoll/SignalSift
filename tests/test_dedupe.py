from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from signalsift.dedupe import article_key, deduplicate_results, normalize_title, normalize_url
from signalsift.models import EvaluationResult, NormalizedItem


def item(
    *,
    item_id: str | None = None,
    url: str | None = "https://example.test/article",
    title: str = "Example Article",
    source_id: str = "example",
) -> NormalizedItem:
    return NormalizedItem(
        id=item_id,
        source_id=source_id,
        title=title,
        url=url,
        published_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


def result(value: NormalizedItem) -> EvaluationResult:
    return EvaluationResult(value, 7, ("supply-chain",), "supply-chain")


def test_normalize_url_removes_tracking_fragment_and_sorts_query() -> None:
    first = normalize_url(
        "HTTPS://ExAmPle.TEST:443/path/?b=2&utm_source=feed&a=3&a=1#section"
    )
    second = normalize_url("https://example.test/path?a=1&a=3&b=2")

    assert first == "https://example.test/path?a=1&a=3&b=2"
    assert first == second


def test_normalize_url_handles_root_idn_and_default_port() -> None:
    assert normalize_url("https://例え.テスト") == "https://xn--r8jz45g.xn--zckzah/"
    assert normalize_url("http://example.test:80/") == "http://example.test/"


def test_article_key_prefers_guid_then_url_then_title() -> None:
    guid_item = item(item_id="stable-id", url="https://one.test")
    assert article_key(guid_item) == article_key(
        item(item_id="stable-id", url="https://two.test", title="Different")
    )

    url_item = item(item_id=None, url="https://example.test/a?utm_medium=rss#x")
    assert article_key(url_item) == article_key(
        item(item_id=None, url="https://example.test/a/")
    )

    title_item = item(item_id=None, url=None, title=" Ｅxample   TITLE ")
    assert normalize_title(title_item.title) == "example title"
    assert article_key(title_item) == article_key(
        item(item_id=None, url=None, title="example title")
    )


def test_url_shaped_guid_is_canonicalized_instead_of_hashed_raw() -> None:
    first = item(
        item_id="https://example.test/a?utm_source=feed",
        url="https://example.test/a?utm_source=feed",
    )
    second = item(
        item_id="https://example.test/a#fragment",
        url="https://example.test/a/",
    )

    assert article_key(first) == article_key(second)


def test_rdf_about_preserves_distinct_in_document_entry_fragments() -> None:
    first = item(
        item_id="https://www.jpcert.or.jp/wr/2026/wr260805.html#1",
        url="https://www.jpcert.or.jp/wr/2026/wr260805.html#1",
        title="Weekly Report: Edge vulnerability",
        source_id="jpcert",
    )
    second = item(
        item_id="https://www.jpcert.or.jp/wr/2026/wr260805.html#2",
        url="https://www.jpcert.or.jp/wr/2026/wr260805.html#2",
        title="Weekly Report: Rails vulnerability",
        source_id="jpcert",
    )
    first = replace(
        first, raw_metadata={"feed_format": "rdf", "id_kind": "rdf_about"}
    )
    second = replace(
        second, raw_metadata={"feed_format": "rdf", "id_kind": "rdf_about"}
    )

    assert article_key(first) != article_key(second)


def test_same_cve_in_different_articles_has_different_keys() -> None:
    first = item(item_id=None, url="https://one.test/cve", title="CVE-2026-12345")
    second = item(item_id=None, url="https://two.test/cve", title="CVE-2026-12345")

    assert article_key(first) != article_key(second)


def test_deduplicate_results_checks_saved_and_same_run_keys() -> None:
    first = result(item(item_id="one"))
    repeated = result(item(item_id="one", title="Repeated"))
    saved = result(item(item_id="saved"))

    unique, duplicate_count = deduplicate_results(
        (first, repeated, saved),
        notified_keys=frozenset({article_key(saved.item)}),
    )

    assert len(unique) == 1
    assert unique[0].article_key == article_key(first.item)
    assert duplicate_count == 2
