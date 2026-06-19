import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.airdrop_monitor import AirdropMonitor


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.request = httpx.Request("GET", "https://aptosfoundation.org/currents")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,
            )


class _FakeClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)

    async def get(self, _url):
        item = self._outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestAirdropMonitor(unittest.IsolatedAsyncioTestCase):
    def _build_monitor(self, root: Path) -> AirdropMonitor:
        cfg = MagicMock()
        cfg.network = "testnet"
        cfg.airdrop.sources = ["aptos_currents"]
        cfg.airdrop.check_interval_hours = 6
        cfg.airdrop.aptos_currents_url = "https://aptosfoundation.org/currents"
        cfg.retry.scraping.attempts = 3
        cfg.retry.scraping.base_delay_seconds = 0.0
        cfg.retry.scraping.max_delay_seconds = 0.0
        cfg.retry.scraping.jitter_ratio = 0.0
        with patch("src.airdrop_monitor.PROJECT_ROOT", root):
            return AirdropMonitor(cfg, MagicMock())

    async def test_fetch_with_retry_recovers_after_transient_error(self):
        with TemporaryDirectory() as tmp:
            monitor = self._build_monitor(Path(tmp))
            monitor.http_backoff_base_seconds = 0.0
            client = _FakeClient(
                [
                    httpx.HTTPError("temporary network issue"),
                    _FakeResponse(status_code=200, text="<html></html>"),
                ]
            )

            html, retries = await monitor._fetch_with_retry(client, monitor.config.airdrop.aptos_currents_url)
            self.assertEqual(html, "<html></html>")
            self.assertEqual(retries, 1)

    async def test_check_all_sources_tracks_quality_and_dedup(self):
        with TemporaryDirectory() as tmp:
            monitor = self._build_monitor(Path(tmp))
            airdrop = {
                "id": "https://aptosfoundation.org/currents/testnet-airdrop",
                "name": "Testnet Airdrop",
                "network": "testnet",
                "value_estimate": 0.0,
                "url": "https://aptosfoundation.org/currents/testnet-airdrop",
            }
            monitor._check_source = AsyncMock(
                return_value=([airdrop, dict(airdrop)], {"parse_errors": 2, "http_retries": 1})
            )

            rows = await monitor.check_all_sources()
            self.assertEqual(len(rows), 1)
            self.assertEqual(monitor.last_ingestion_quality["new_total"], 1)
            self.assertEqual(monitor.last_ingestion_quality["duplicates_filtered"], 1)
            self.assertEqual(monitor.last_ingestion_quality["parse_errors"], 2)
            self.assertEqual(monitor.last_ingestion_quality["http_retries"], 1)

    def test_mark_seen_trims_state_growth(self):
        with TemporaryDirectory() as tmp:
            monitor = self._build_monitor(Path(tmp))
            monitor.max_seen_airdrops = 2

            monitor._mark_seen({"url": "https://aptosfoundation.org/currents/a"})
            monitor._mark_seen({"url": "https://aptosfoundation.org/currents/b"})
            monitor._mark_seen({"url": "https://aptosfoundation.org/currents/c"})

            self.assertEqual(
                monitor.state["seen_airdrops"],
                [
                    "https://aptosfoundation.org/currents/b",
                    "https://aptosfoundation.org/currents/c",
                ],
            )
            self.assertNotIn("https://aptosfoundation.org/currents/a", monitor._seen_index)

    def test_should_check_gracefully_handles_invalid_timestamp(self):
        with TemporaryDirectory() as tmp:
            monitor = self._build_monitor(Path(tmp))
            monitor.state["last_check"] = "not-a-timestamp"
            should_run, reason = monitor.should_check()
            self.assertTrue(should_run)
            self.assertIn("Invalid", reason)


if __name__ == "__main__":
    unittest.main()
