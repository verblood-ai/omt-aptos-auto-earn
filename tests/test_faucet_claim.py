import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.faucet import FaucetManager


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_post = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, params=None, headers=None):
        self.last_post = {"url": url, "params": params, "headers": headers or {}}
        return self._response


class TestFaucetClaim(unittest.IsolatedAsyncioTestCase):
    def _build_manager(self, tmp_root: Path) -> tuple[FaucetManager, MagicMock]:
        cfg = MagicMock()
        cfg.network = "devnet"
        cfg.faucet.max_claims_per_day = 3
        cfg.faucet.cooldown_hours = 0
        cfg.faucet.api_url = "https://faucet.devnet.aptoslabs.com/mint"
        cfg.faucet.amount = 100_000_000
        cfg.retry.faucet_http.attempts = 2
        cfg.retry.faucet_http.base_delay_seconds = 0.0
        cfg.retry.faucet_http.max_delay_seconds = 0.0
        cfg.retry.faucet_http.jitter_ratio = 0.0

        db = MagicMock()
        wallet = MagicMock()
        wallet.address = "0xabc"

        (tmp_root / "data").mkdir(parents=True, exist_ok=True)
        with patch("src.faucet.PROJECT_ROOT", tmp_root):
            manager = FaucetManager(cfg, db, wallet)
        return manager, db

    async def test_claim_success_updates_state_and_db(self):
        with TemporaryDirectory() as tmp:
            manager, db = self._build_manager(Path(tmp))
            fake_client = _FakeAsyncClient(_FakeResponse(status_code=200, json_data=["0xdeadbeef"]))

            with patch("src.faucet.httpx.AsyncClient", return_value=fake_client):
                ok = await manager.claim()

            self.assertTrue(ok)
            self.assertEqual(manager._net_slice()["claims_today"], 1)
            self.assertIsNotNone(manager._net_slice()["last_claim_timestamp"])
            db.insert_faucet_claim.assert_called_once()
            kwargs = db.insert_faucet_claim.call_args.kwargs
            self.assertEqual(kwargs["status"], "success")
            self.assertEqual(kwargs["tx_hash"], "0xdeadbeef")
            self.assertEqual(fake_client.last_post["params"]["address"], "0xabc")

    async def test_claim_http_4xx_records_failed_claim(self):
        with TemporaryDirectory() as tmp:
            manager, db = self._build_manager(Path(tmp))
            fake_client = _FakeAsyncClient(_FakeResponse(status_code=429, text="rate limit"))

            with patch("src.faucet.httpx.AsyncClient", return_value=fake_client):
                ok = await manager.claim()

            self.assertFalse(ok)
            self.assertEqual(manager._net_slice()["claims_today"], 0)
            db.insert_faucet_claim.assert_called_once()
            kwargs = db.insert_faucet_claim.call_args.kwargs
            self.assertEqual(kwargs["status"], "failed")
            self.assertIn("HTTP 429", kwargs["error_message"])


if __name__ == "__main__":
    unittest.main()
