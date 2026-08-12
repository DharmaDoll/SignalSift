from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import replace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from signalsift.models import EvaluationResult, NormalizedItem


TRACKING_PARAMETERS = frozenset({"fbclid", "gclid", "msclkid"})


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("article URL must be absolute HTTP(S)")
    if parts.username is not None or parts.password is not None:
        raise ValueError("article URL must not contain credentials")

    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("article URL contains an invalid port") from exc
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"

    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_parameter(key)
    ]
    query_pairs.sort(key=lambda pair: (pair[0], pair[1]))
    return urlunsplit((scheme, host, path, urlencode(query_pairs, doseq=True), ""))


def normalize_title(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def article_key(item: NormalizedItem, *, stable_id: bool = True) -> str:
    if stable_id and item.id and item.id.strip():
        item_id = item.id.strip()
        if _looks_like_http_url(item_id):
            try:
                material = f"url:{normalize_url(item.url or item_id)}"
            except ValueError:
                material = f"title:{item.source_id}:{normalize_title(item.title)}"
        else:
            material = f"guid:{item.source_id}:{item_id}"
    elif item.url:
        try:
            material = f"url:{normalize_url(item.url)}"
        except ValueError:
            material = f"title:{item.source_id}:{normalize_title(item.title)}"
    else:
        material = f"title:{item.source_id}:{normalize_title(item.title)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def deduplicate_results(
    results: tuple[EvaluationResult, ...],
    *,
    notified_keys: frozenset[str] = frozenset(),
) -> tuple[tuple[EvaluationResult, ...], int]:
    seen = set(notified_keys)
    unique: list[EvaluationResult] = []
    duplicate_count = 0
    for result in results:
        key = article_key(result.item)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        unique.append(replace(result, article_key=key))
    return tuple(unique), duplicate_count


def _is_tracking_parameter(key: str) -> bool:
    normalized = key.casefold()
    return normalized.startswith("utm_") or normalized in TRACKING_PARAMETERS


def _looks_like_http_url(value: str) -> bool:
    return urlsplit(value).scheme.casefold() in {"http", "https"}
