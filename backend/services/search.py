"""Tavily search client, SSRF-safe canonical URL normalizer, prompt-injection sanitizer, and credibility scorer."""
from __future__ import annotations

import asyncio
import ipaddress
import random
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from backend.models.schemas import CredibilityBreakdown, SourceRecord
from backend.services.llm import AsyncRateLimiter

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}

GOV_EDU_DOMAINS = {
    "nist.gov",
    "nasa.gov",
    "nih.gov",
    "cdc.gov",
    "fda.gov",
    "energy.gov",
    "ietf.org",
    "w3.org",
    "iso.org",
    "who.int",
    "europa.eu",
    "cisa.gov",
}

ACADEMIC_DOMAINS = {
    "arxiv.org",
    "nature.com",
    "science.org",
    "ieee.org",
    "acm.org",
    "dl.acm.org",
    "springer.com",
    "ncbi.nlm.nih.gov",
    "neurips.cc",
    "openreview.net",
    "jmlr.org",
    "aclweb.org",
    "aclanthology.org",
    "pnas.org",
    "mitpress.mit.edu",
    "stanford.edu",
    "berkeley.edu",
    "cmu.edu",
}

ESTABLISHED_TECH_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "arstechnica.com",
    "huggingface.co",
    "openai.com",
    "anthropic.com",
    "ai.meta.com",
    "engineering.fb.com",
    "research.google",
    "deepmind.google",
    "cloud.google.com",
    "aws.amazon.com",
    "microsoft.com",
    "nvidia.com",
    "developer.nvidia.com",
    "github.com",
    "python.org",
    "docs.python.org",
    "langchain.com",
    "blog.langchain.dev",
}

LOW_TRUST_DOMAINS = {
    "reddit.com",
    "quora.com",
    "medium.com",
    "blogspot.com",
    "substack.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
}

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"</?untrusted_source[^>]*>", re.IGNORECASE),
]


class SSRFValidationError(ValueError):
    """Raised when a URL uses a forbidden scheme or resolves to a private/loopback host."""


def canonicalize_and_validate_url(raw_url: str) -> tuple[str, str]:
    """Validate URL against SSRF vectors and return (canonical_url, normalized_domain)."""
    parsed = urlparse(raw_url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFValidationError(f"Disallowed URL scheme '{scheme}'. Only http and https are permitted.")

    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        raise SSRFValidationError("URL is missing a valid hostname.")

    if hostname in ("localhost", "localhost.localdomain") or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise SSRFValidationError(f"SSRF guard blocked local hostname '{hostname}'.")

    try:
        ip_obj = ipaddress.ip_address(hostname)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise SSRFValidationError(f"SSRF guard blocked non-public IP address '{hostname}'.")
    except ValueError:
        if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", hostname):
            raise SSRFValidationError(f"Invalid public domain format '{hostname}'.")

    domain = hostname[4:] if hostname.startswith("www.") else hostname
    port = parsed.port
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{domain}:{port}"
    else:
        netloc = domain

    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS
    ]
    filtered_query.sort(key=lambda kv: kv[0])
    query_str = urlencode(filtered_query)

    canonical = urlunparse((scheme, netloc, path, "", query_str, ""))
    domain = hostname[4:] if hostname.startswith("www.") else hostname
    return canonical, domain


def sanitize_untrusted_snippet(text: str, max_chars: int = 1200) -> str:
    """Sanitize untrusted web text against prompt injection before passing to LLM prompts."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    for pattern in INJECTION_PATTERNS:
        cleaned = pattern.sub("[REDACTED-INSTRUCTION-PATTERN]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def _classify_domain(domain: str) -> tuple[str, float]:
    if (
        domain.endswith(".gov")
        or domain.endswith(".mil")
        or domain in GOV_EDU_DOMAINS
        or any(domain.endswith("." + d) for d in GOV_EDU_DOMAINS)
    ):
        return "gov_edu_standards", 0.95
    if (
        domain.endswith(".edu")
        or domain in ACADEMIC_DOMAINS
        or any(domain.endswith("." + d) for d in ACADEMIC_DOMAINS)
    ):
        return "academic_journal", 0.92
    if domain in ESTABLISHED_TECH_DOMAINS or any(domain.endswith("." + d) for d in ESTABLISHED_TECH_DOMAINS):
        return "established_tech_news", 0.82
    if domain in LOW_TRUST_DOMAINS or any(domain.endswith("." + d) for d in LOW_TRUST_DOMAINS):
        return "low_trust_or_ugc", 0.38
    return "general_web", 0.65


def _score_recency(published_date: str | None) -> tuple[float, str]:
    if not published_date:
        return 0.65, "unlisted date (neutral 0.65)"
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", published_date)
    if not year_match:
        return 0.65, "unparsed date (neutral 0.65)"
    year = int(year_match.group(1))
    current_year = datetime.now(timezone.utc).year
    age = max(0, current_year - year)
    if age <= 1:
        return 0.95, f"recent ({year}, 0.95)"
    if age <= 3:
        return 0.85, f"moderately recent ({year}, 0.85)"
    if age <= 6:
        return 0.70, f"older ({year}, 0.70)"
    return 0.50, f"archival ({year}, 0.50)"


def score_source_credibility(
    *,
    canonical_url: str,
    domain: str,
    published_date: str | None,
    tavily_score: float,
) -> CredibilityBreakdown:
    """Compute a transparent, documented credibility score in [0.0, 1.0]."""
    domain_class, domain_score = _classify_domain(domain)
    https_score = 1.0 if canonical_url.startswith("https://") else 0.2
    recency_score, recency_label = _score_recency(published_date)
    clamped_tavily = max(0.0, min(1.0, float(tavily_score)))

    composite = round(
        (0.35 * domain_score)
        + (0.10 * https_score)
        + (0.25 * recency_score)
        + (0.30 * clamped_tavily),
        3,
    )
    reasoning = (
        f"Domain '{domain}' [{domain_class}={domain_score:.2f}*0.35] + "
        f"{'HTTPS' if https_score == 1.0 else 'HTTP'} [{https_score:.2f}*0.10] + "
        f"Recency [{recency_label}*0.25] + "
        f"Tavily [{clamped_tavily:.2f}*0.30] => {composite:.3f}"
    )
    return CredibilityBreakdown(
        domain_class=domain_class,  # type: ignore[arg-type]
        domain_score=domain_score,
        https_score=https_score,
        recency_score=recency_score,
        tavily_relevance_score=clamped_tavily,
        composite_score=composite,
        reasoning=reasoning,
    )


class TavilySearchClient:
    """Async Tavily search client with exponential backoff + jitter, deduplication, and credibility scoring."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        rate_limiter: AsyncRateLimiter | None = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        stub_searcher: Callable[[str, str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.rate_limiter = rate_limiter or AsyncRateLimiter(30)
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._transport = transport
        self._stub_searcher = stub_searcher

    async def search_section(
        self,
        *,
        run_id: str,
        section_id: str,
        query: str,
        existing_sources: list[SourceRecord],
        max_results: int = 4,
    ) -> list[SourceRecord]:
        """Search Tavily for a section, deduplicate by canonical_url across the run, and score credibility."""
        await self.rate_limiter.acquire()
        if self._stub_searcher is not None:
            raw_results = self._stub_searcher(section_id, query)
        else:
            raw_results = await self._fetch_tavily(query, max_results=max_results)

        seen_canonical = {src.canonical_url for src in existing_sources}
        next_idx = len(existing_sources) + 1
        new_sources: list[SourceRecord] = []

        for item in raw_results:
            raw_url = str(item.get("url", "")).strip()
            if not raw_url:
                continue
            try:
                canonical_url, domain = canonicalize_and_validate_url(raw_url)
            except SSRFValidationError:
                continue

            if canonical_url in seen_canonical:
                continue

            raw_snippet = str(item.get("content") or item.get("snippet") or "").strip()
            snippet = sanitize_untrusted_snippet(raw_snippet)
            if len(snippet) < 20:
                continue

            title = sanitize_untrusted_snippet(str(item.get("title") or domain), max_chars=200)
            published_date = item.get("published_date")
            tavily_score = float(item.get("score", 0.75))

            breakdown = score_source_credibility(
                canonical_url=canonical_url,
                domain=domain,
                published_date=str(published_date) if published_date else None,
                tavily_score=tavily_score,
            )
            source_id = f"S{next_idx}"
            next_idx += 1
            seen_canonical.add(canonical_url)

            new_sources.append(
                SourceRecord(
                    source_id=source_id,
                    run_id=run_id,
                    section_id=section_id,
                    url=raw_url,
                    canonical_url=canonical_url,
                    domain=domain,
                    title=title,
                    snippet=snippet,
                    published_date=str(published_date) if published_date else None,
                    tavily_score=breakdown.tavily_relevance_score,
                    credibility_score=breakdown.composite_score,
                    credibility_breakdown=breakdown,
                )
            )

        return new_sources

    async def _fetch_tavily(self, query: str, max_results: int = 4) -> list[dict[str, Any]]:
        if not self._api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is not set. Provide TAVILY_API_KEY in environment or enable NEXUS_STUB_APIS=true."
            )
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "max_results": max_results,
        }
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(f"{self.base_url}/search", json=payload)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if attempt < self.max_retries:
                            delay = self.base_backoff_seconds * (2**attempt) + random.uniform(0.01, 0.25)
                            await asyncio.sleep(delay)
                            continue
                        raise RuntimeError(f"Tavily API HTTP {resp.status_code} after retries.")
                    if resp.status_code >= 400:
                        raise RuntimeError(f"Tavily API error HTTP {resp.status_code}: {resp.text[:250]}")
                    data = resp.json()
                    results = data.get("results", [])
                    return results if isinstance(results, list) else []
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.base_backoff_seconds * (2**attempt))
                        continue
                    raise RuntimeError(f"Tavily network error: {exc}") from exc
        return []
