from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from signalsift.models import EvaluationResult, FilterConfig, NamedRule, NormalizedItem, SourceConfig


ASCII_WORD_CHARACTER = r"a-z0-9"


def item_match_text(item: NormalizedItem) -> str:
    fields = (
        item.title,
        item.summary,
        item.content,
        *item.categories,
        *item.external_ids,
    )
    return normalize_match_text(" ".join(field for field in fields if field))


def normalize_match_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def term_matches(text: str, term: str) -> bool:
    normalized_term = normalize_match_text(term)
    if not normalized_term:
        return False
    if _is_ascii_prefix_term(normalized_term):
        pattern = rf"(?<![{ASCII_WORD_CHARACTER}]){re.escape(normalized_term)}"
        return re.search(pattern, text) is not None
    if _is_ascii_word_or_phrase(normalized_term):
        pattern = (
            rf"(?<![{ASCII_WORD_CHARACTER}])"
            rf"{re.escape(normalized_term)}"
            rf"(?![{ASCII_WORD_CHARACTER}])"
        )
        return re.search(pattern, text) is not None
    return normalized_term in text


def passes_source_filter(item: NormalizedItem, source: SourceConfig) -> bool:
    if item.source_id != source.id:
        raise ValueError("item source_id does not match source configuration")
    source_filter = source.source_filter
    if source_filter is None:
        return True
    text = item_match_text(item)
    if any(term_matches(text, term) for term in source_filter.exclude):
        return False
    if source_filter.include_any and not any(
        term_matches(text, term) for term in source_filter.include_any
    ):
        return False
    return True


def evaluate_item(
    item: NormalizedItem,
    source: SourceConfig,
    config: FilterConfig,
    *,
    force_notify: bool = False,
) -> EvaluationResult | None:
    """Return an explainable result only when an item should be selected."""

    if not passes_source_filter(item, source):
        return None
    text = item_match_text(item)
    priority_score = dict(config.source_priority_score)[source.priority]
    score = priority_score

    topic_matches: list[tuple[NamedRule, tuple[str, ...]]] = []
    for rule in config.rules:
        matched_terms = _matched_rule_terms(text, rule)
        if matched_terms:
            topic_matches.append((rule, matched_terms))
            score += rule.score

    boost_matches: list[tuple[NamedRule, tuple[str, ...]]] = []
    for boost in config.boosts:
        matched_terms = _matched_rule_terms(text, boost)
        if matched_terms:
            boost_matches.append((boost, matched_terms))
            score += boost.score

    negative_reason: str | None = None
    strong_negative = _first_matching_term(text, config.negative_terms.terms)
    mild_negative = _first_matching_term(text, config.negative_terms.mild.terms)
    if strong_negative is not None:
        score += config.negative_terms.score
        negative_reason = (
            f"negative:{_reason_term(strong_negative)}:{config.negative_terms.score}"
        )
    elif mild_negative is not None:
        score += config.negative_terms.mild.score
        negative_reason = (
            f"negative:{_reason_term(mild_negative)}:{config.negative_terms.mild.score}"
        )

    watch_matches = tuple(
        term for term in config.watch_terms.terms if term_matches(text, term)
    )
    if watch_matches:
        score += config.watch_terms.score

    forced = force_notify and source.force_notify_new_entries
    if not forced and (not topic_matches or score < config.notification.threshold):
        return None

    reasons: list[str] = []
    reasons.extend(_reason_name(rule.name) for rule, _ in topic_matches)
    reasons.extend(
        _reason_term(term)
        for _, matched_terms in topic_matches
        for term in matched_terms
    )
    reasons.extend(_reason_name(boost.name) for boost, _ in boost_matches)
    if negative_reason is not None:
        reasons.append(negative_reason)
    reasons.extend(_reason_term(term) for term in watch_matches)
    reasons.append(f"source-priority:{source.priority}")
    if forced:
        reasons.append(f"force-notify:{source.id}")

    matched_topic = _reason_name(topic_matches[0][0].name) if topic_matches else "forced"
    return EvaluationResult(
        item=item,
        score=score,
        why_matched=_stable_unique(reasons),
        matched_topic=matched_topic,
    )


def _matched_rule_terms(text: str, rule: NamedRule) -> tuple[str, ...]:
    if rule.any:
        match = _first_matching_term(text, rule.any)
        return (match,) if match is not None else ()
    matches: list[str] = []
    for group in rule.all_groups:
        match = _first_matching_term(text, group)
        if match is None:
            return ()
        matches.append(match)
    return tuple(matches)


def _first_matching_term(text: str, terms: Iterable[str]) -> str | None:
    return next((term for term in terms if term_matches(text, term)), None)


def _is_ascii_word_or_phrase(term: str) -> bool:
    return all(character.isascii() and (character.isalnum() or character.isspace()) for character in term)


def _is_ascii_prefix_term(term: str) -> bool:
    return (
        len(term) > 1
        and not term[-1].isalnum()
        and all(character.isascii() and (character.isalnum() or character in "-_./") for character in term)
    )


def _reason_name(value: str) -> str:
    return normalize_match_text(value).replace("_", "-").replace(" ", "-")


def _reason_term(value: str) -> str:
    return normalize_match_text(value).replace(" ", "-")


def _stable_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
