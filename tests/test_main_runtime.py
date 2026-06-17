import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.main import AptosAutoEarn


class TestMainRuntime(unittest.IsolatedAsyncioTestCase):
    def _build_orchestrator(self, *, min_interval_minutes: int) -> AptosAutoEarn:
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        cfg.activity.enabled = False
        cfg.activity.min_interval_minutes = min_interval_minutes

        wallet = MagicMock()
        wallet.address = "0xabc"
        wallet.get_balance = AsyncMock(return_value=1.0)
        wallet.close = AsyncMock()

        faucet = MagicMock()
        faucet.can_claim.return_value = (False, "skip")
        faucet.claim = AsyncMock(return_value=False)
        faucet.format_amount.return_value = "100000000 octas (1.00000000 APT)"

        with patch("src.main.Config.load", return_value=cfg), \
            patch("src.main.MetricsDB", return_value=MagicMock()), \
            patch("src.main.WalletManager", return_value=wallet), \
            patch("src.main.FaucetManager", return_value=faucet), \
            patch("src.main.AirdropMonitor", return_value=MagicMock()), \
            patch("src.main.AptosAutoEarn._setup_logging", return_value=None), \
            patch("src.main.AptosAutoEarn._setup_signal_handlers", return_value=None):
            orchestrator = AptosAutoEarn()
        return orchestrator

    async def test_activity_cycle_throttles_by_min_interval(self):
        orchestrator = self._build_orchestrator(min_interval_minutes=30)
        module = MagicMock()
        module.module_name = "lending"
        module.can_run.return_value = (True, "OK")
        module.run = AsyncMock(
            return_value={"success": True, "actions": 1, "duration": 0.1}
        )
        orchestrator.activity_modules = [module]

        await orchestrator.run_activity_cycle()
        await orchestrator.run_activity_cycle()

        self.assertEqual(module.run.await_count, 1)
        self.assertEqual(orchestrator.wallet.get_balance.await_count, 1)

    async def test_dex_preflight_failure_skips_dex_module(self):
        orchestrator = self._build_orchestrator(min_interval_minutes=0)
        dex_module = MagicMock()
        dex_module.module_name = "dex_swap"
        dex_module.can_run.return_value = (True, "OK")
        dex_module.run = AsyncMock(
            return_value={"success": True, "actions": 1, "duration": 0.1}
        )
        nft_module = MagicMock()
        nft_module.module_name = "nft_mint"
        nft_module.can_run.return_value = (True, "OK")
        nft_module.run = AsyncMock(
            return_value={"success": True, "actions": 1, "duration": 0.1}
        )
        orchestrator.activity_modules = [dex_module, nft_module]
        orchestrator._ensure_dex_preflight = AsyncMock(return_value=False)
        orchestrator._dex_preflight_error = "missing modules: scripts_v2"

        await orchestrator.run_activity_cycle()

        orchestrator._ensure_dex_preflight.assert_awaited_once()
        dex_module.run.assert_not_awaited()
        nft_module.run.assert_awaited_once()

    async def test_enqueue_scheduled_job_deduplicates(self):
        orchestrator = self._build_orchestrator(min_interval_minutes=0)
        orchestrator.run_activity_cycle = AsyncMock(return_value=None)

        orchestrator._enqueue_scheduled_job("activity")
        orchestrator._enqueue_scheduled_job("activity")
        self.assertEqual(orchestrator._scheduled_job_queue.qsize(), 1)

        await orchestrator._run_queued_jobs()

        orchestrator.run_activity_cycle.assert_awaited_once()
        self.assertEqual(orchestrator._scheduled_job_queue.qsize(), 0)
        self.assertEqual(len(orchestrator._scheduled_jobs_enqueued), 0)


if __name__ == "__main__":
    unittest.main()
