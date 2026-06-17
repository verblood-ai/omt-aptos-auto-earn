"""Faucet state: per-network limits for zero-start on each chain."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.faucet import FaucetManager


class TestFaucetPerNetwork(unittest.TestCase):
    def test_legacy_flat_file_allows_claim_on_other_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir(parents=True)
            state_path = root / "data" / "faucet_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "claims_today": 1,
                        "last_claim_date": "2026-04-20",
                        "last_claim_timestamp": "2026-04-20T12:00:00",
                    }
                ),
                encoding="utf-8",
            )

            cfg = MagicMock()
            cfg.network = "testnet"
            cfg.faucet.max_claims_per_day = 1
            cfg.faucet.cooldown_hours = 24
            # Devnet URL: публичный /mint без JWT (в тесте проверяем только раздельный state по сети).
            cfg.faucet.api_url = "https://faucet.devnet.aptoslabs.com/mint"
            cfg.faucet.amount = 100_000_000.0

            wallet = MagicMock()
            db = MagicMock()

            with patch("src.faucet.PROJECT_ROOT", root):
                fm = FaucetManager(cfg, db, wallet)

            self.assertIn("by_network", fm.state)
            self.assertEqual(fm.state["by_network"]["devnet"]["claims_today"], 1)
            can, reason = fm.can_claim()
            self.assertTrue(can, reason)
            self.assertEqual(fm._net_slice()["claims_today"], 0)


class TestFaucetTestnetJwt(unittest.TestCase):
    def test_testnet_faucet_requires_jwt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir(parents=True)
            (root / "data" / "faucet_state.json").write_text('{"by_network": {}}', encoding="utf-8")

            cfg = MagicMock()
            cfg.network = "testnet"
            cfg.faucet.max_claims_per_day = 1
            cfg.faucet.cooldown_hours = 24
            cfg.faucet.api_url = "https://faucet.testnet.aptoslabs.com/mint"
            cfg.faucet.amount = 100_000_000.0

            with patch.object(FaucetManager, "_faucet_jwt", return_value=""):
                with patch("src.faucet.PROJECT_ROOT", root):
                    fm = FaucetManager(cfg, MagicMock(), MagicMock())
                    can, reason = fm.can_claim()
            self.assertFalse(can)
            self.assertIn("APTOS_FAUCET_JWT", reason)


if __name__ == "__main__":
    unittest.main()
