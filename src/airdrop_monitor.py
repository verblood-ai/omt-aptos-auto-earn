"""Airdrop monitoring module."""

import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from .database import MetricsDB
from .config import Config, PROJECT_ROOT

RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _parse_aptos_currents_html_with_stats(
    html: str,
    page_url: str,
    network: str,
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Parse Currents links with quality counters for ingestion logs."""
    stats: Dict[str, int] = {
        "links_total": 0,
        "links_currents": 0,
        "links_keyword_match": 0,
        "parse_errors": 0,
        "duplicates_dropped": 0,
    }
    if not isinstance(html, str) or not html.strip():
        return [], stats

    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, flags=re.IGNORECASE)
    stats["links_total"] = len(hrefs)
    results: List[Dict[str, Any]] = []

    keywords = (
        "airdrop",
        "incentive",
        "reward",
        "quest",
        "campaign",
        "testnet",
        "devnet",
        "mainnet",
        "launch",
        "token",
        "nft",
    )

    for href in hrefs:
        try:
            raw_href = (href or "").strip()
            if not raw_href or raw_href.startswith("#"):
                continue
            if raw_href.lower().startswith(("mailto:", "javascript:")):
                continue

            absolute = urljoin(page_url, raw_href).strip()
            parsed = urlparse(absolute)
            host = (parsed.netloc or "").lower()
            path = (parsed.path or "").rstrip("/")
            if parsed.scheme not in {"http", "https"}:
                continue
            if host != "aptosfoundation.org" or not path.startswith("/currents/"):
                continue

            stats["links_currents"] += 1
            slug = path.split("/")[-1].strip().lower()
            if not slug:
                continue

            search_blob = f"{slug} {absolute}".lower()
            if not any(keyword in search_blob for keyword in keywords):
                continue

            stats["links_keyword_match"] += 1
            canonical_url = f"{parsed.scheme}://{parsed.netloc}{path}"
            title = re.sub(r"[-_]+", " ", slug).strip().title() or "Currents Opportunity"
            results.append(
                {
                    "id": canonical_url,
                    "name": title,
                    "network": network,
                    "value_estimate": 0.0,
                    "url": canonical_url,
                }
            )
        except Exception:
            # Graceful degradation: keep processing other links.
            stats["parse_errors"] += 1
            continue

    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in results:
        ident = item["id"]
        if ident in seen:
            stats["duplicates_dropped"] += 1
            continue
        seen.add(ident)
        unique.append(item)

    return unique, stats


def parse_aptos_currents_html(html: str, page_url: str, network: str) -> List[Dict[str, Any]]:
    """
    Extract candidate airdrop-related Currents links from HTML (no HTTP).

    Used by tests and by AirdropMonitor network fetch path.
    """
    rows, _stats = _parse_aptos_currents_html_with_stats(html, page_url, network)
    return rows


class AirdropMonitor:
    """Monitors airdrop opportunities."""

    def __init__(self, config: Config, db: MetricsDB):
        """Initialize airdrop monitor."""
        self.config = config
        self.db = db
        self.sources = config.airdrop.sources
        self.check_interval_hours = config.airdrop.check_interval_hours
        self.max_seen_airdrops = 5000
        self.http_max_retries = 3
        self.http_backoff_base_seconds = 1.0
        self.last_ingestion_quality: Dict[str, Any] = {}

        # State file for tracking last check and seen airdrops
        self.state_file = PROJECT_ROOT / "data" / "airdrop_state.json"
        self.state = self._load_state()
        self._seen_index = set(self.state["seen_airdrops"])

    def _default_state(self) -> Dict[str, Any]:
        return {
            "last_check": None,
            "seen_airdrops": [],
        }

    def _normalize_seen_airdrops(self, seen_airdrops: Any) -> List[str]:
        items = seen_airdrops if isinstance(seen_airdrops, list) else []
        normalized: List[str] = []
        seen = set()
        for raw in items:
            if not isinstance(raw, str):
                continue
            ident = raw.strip()
            if not ident or ident in seen:
                continue
            seen.add(ident)
            normalized.append(ident)
        if len(normalized) > self.max_seen_airdrops:
            trimmed = len(normalized) - self.max_seen_airdrops
            normalized = normalized[-self.max_seen_airdrops:]
            logger.warning(
                "Airdrop state trimmed {} old seen items to control growth (max={})",
                trimmed,
                self.max_seen_airdrops,
            )
        return normalized

    def _load_state(self) -> Dict[str, Any]:
        """Load monitor state from file."""
        if not self.state_file.exists():
            return self._default_state()
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load airdrop state (resetting): {}", exc)
            return self._default_state()

        state = self._default_state()
        state["last_check"] = raw.get("last_check")
        state["seen_airdrops"] = self._normalize_seen_airdrops(raw.get("seen_airdrops"))
        return state

    def _save_state(self):
        """Save monitor state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    async def check_all_sources(self) -> List[Dict[str, Any]]:
        """
        Check all configured sources for new airdrops.
        Returns list of new airdrops found.
        """
        started = time.perf_counter()
        new_airdrops: List[Dict[str, Any]] = []
        quality = {
            "sources_checked": 0,
            "sources_failed": 0,
            "found_total": 0,
            "new_total": 0,
            "duplicates_filtered": 0,
            "parse_errors": 0,
            "http_retries": 0,
            "duration_ms": 0.0,
        }

        for source in self.sources:
            try:
                source_started = time.perf_counter()
                logger.info("Checking {} for Aptos airdrops...", source)
                source_airdrops, source_quality = await self._check_source(source)
                quality["sources_checked"] += 1
                quality["found_total"] += len(source_airdrops)
                quality["parse_errors"] += int(source_quality.get("parse_errors", 0))
                quality["http_retries"] += int(source_quality.get("http_retries", 0))
                for airdrop in source_airdrops:
                    if self._is_new_airdrop(airdrop):
                        new_airdrops.append(airdrop)
                        self._mark_seen(airdrop)
                        quality["new_total"] += 1
                    else:
                        quality["duplicates_filtered"] += 1
                latency_ms = (time.perf_counter() - source_started) * 1000
                logger.info(
                    "Airdrop ingestion source={} found={} new={} retries={} parse_errors={} latency_ms={:.1f}",
                    source,
                    len(source_airdrops),
                    quality["new_total"],
                    source_quality.get("http_retries", 0),
                    source_quality.get("parse_errors", 0),
                    latency_ms,
                )
            except Exception as e:
                quality["sources_failed"] += 1
                logger.error("Error checking {}: {}", source, e)

        # Update last check time
        self.state["last_check"] = datetime.utcnow().isoformat()
        self._save_state()
        quality["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        self.last_ingestion_quality = quality
        logger.info(
            "Airdrop ingestion quality: checked={} failed={} found={} new={} duplicates={} parse_errors={} retries={} duration_ms={}",
            quality["sources_checked"],
            quality["sources_failed"],
            quality["found_total"],
            quality["new_total"],
            quality["duplicates_filtered"],
            quality["parse_errors"],
            quality["http_retries"],
            quality["duration_ms"],
        )

        return new_airdrops

    async def _check_source(self, source: str) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Check a specific source for airdrops.
        """
        source_key = (source or "").strip().lower()

        if source_key in {"aptos_currents", "aptosfoundation", "aptos_foundation"}:
            return await self._check_aptos_currents()

        if source_key in {"galxe", "zealy", "dappradar"}:
            logger.warning(
                f"{source_key} integration requires credentials/API keys; skipping until configured"
            )
            return [], {"parse_errors": 0, "http_retries": 0}

        logger.warning(f"Unknown airdrop source: {source}")
        return [], {"parse_errors": 0, "http_retries": 0}

    async def _fetch_with_retry(self, client: httpx.AsyncClient, url: str) -> tuple[Optional[str], int]:
        retries = 0
        for attempt in range(1, self.http_max_retries + 1):
            try:
                response = await client.get(url)
                if response.status_code in RETRYABLE_HTTP_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"Retryable HTTP status: {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.text, retries
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                is_retryable = status in RETRYABLE_HTTP_STATUS_CODES
                if attempt == self.http_max_retries or not is_retryable:
                    logger.error("Currents fetch failed with HTTP {} (attempt {}/{})", status, attempt, self.http_max_retries)
                    return None, retries
            except httpx.HTTPError as exc:
                if attempt == self.http_max_retries:
                    logger.error("Currents fetch failed after {} attempts: {}", self.http_max_retries, exc)
                    return None, retries

            retries += 1
            delay = self.http_backoff_base_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Currents fetch retry in {:.1f}s (attempt {}/{})",
                delay,
                attempt + 1,
                self.http_max_retries,
            )
            await asyncio.sleep(delay)

        return None, retries

    async def _check_aptos_currents(self) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
        """Parse Aptos Foundation Currents listing for ecosystem-relevant links."""
        url = self.config.airdrop.aptos_currents_url
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "aptos-auto-earn/1.0"},
        ) as client:
            html, retries = await self._fetch_with_retry(client, url)
        if html is None:
            return [], {"parse_errors": 0, "http_retries": retries}

        rows, stats = _parse_aptos_currents_html_with_stats(html, url, self.config.network)
        return rows, {
            "parse_errors": int(stats.get("parse_errors", 0)),
            "http_retries": retries,
        }

    def _is_new_airdrop(self, airdrop: Dict[str, Any]) -> bool:
        """Check if airdrop is new (not seen before)."""
        identifier = airdrop.get("url") or airdrop.get("id")
        return bool(identifier) and identifier not in self._seen_index

    def _mark_seen(self, airdrop: Dict[str, Any]):
        """Mark an airdrop as seen."""
        identifier = airdrop.get("url") or airdrop.get("id")
        if identifier and identifier not in self._seen_index:
            self.state["seen_airdrops"].append(identifier)
            self._seen_index.add(identifier)
        while len(self.state["seen_airdrops"]) > self.max_seen_airdrops:
            dropped = self.state["seen_airdrops"].pop(0)
            self._seen_index.discard(dropped)

    def should_check(self) -> tuple[bool, str]:
        """Check if it's time to run airdrop check."""
        last_check = self.state.get("last_check")
        if not last_check:
            return True, "Never checked before"

        try:
            last_time = datetime.fromisoformat(last_check)
        except (TypeError, ValueError):
            logger.warning("Airdrop state has invalid last_check timestamp: {}", last_check)
            return True, "Invalid last_check state"
        next_check = last_time + timedelta(hours=self.check_interval_hours)
        if datetime.utcnow() < next_check:
            remaining = next_check - datetime.utcnow()
            return False, f"Next check in {remaining}"

        return True, "OK"
