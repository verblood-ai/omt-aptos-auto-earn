import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.main import AptosAutoEarn


class _ScheduleCall:
    def __init__(self, sink: list[dict], interval: int):
        self._sink = sink
        self._interval = interval
        self._unit = ""
        self._time = ""

    @property
    def day(self):
        self._unit = "day"
        return self

    @property
    def hours(self):
        self._unit = "hours"
        return self

    def at(self, value: str):
        self._time = value
        return self

    def do(self, _func, *args, **_kwargs):
        self._sink.append(
            {
                "interval": self._interval,
                "unit": self._unit,
                "time": self._time,
                "args": args,
            }
        )
        return self


class TestMainOrchestrator(unittest.IsolatedAsyncioTestCase):
    def _build_orchestrator(self) -> AptosAutoEarn:
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        cfg.activity.enabled = False

        wallet = MagicMock()
        wallet.address = "0xabc"
        wallet.close = AsyncMock()
        wallet.get_balance = AsyncMock(return_value=0.0)

        with patch("src.main.Config.load", return_value=cfg), \
            patch("src.main.MetricsDB", return_value=MagicMock()), \
            patch("src.main.WalletManager", return_value=wallet), \
            patch("src.main.FaucetManager", return_value=MagicMock()), \
            patch("src.main.AirdropMonitor", return_value=MagicMock()), \
            patch("src.main.AptosAutoEarn._setup_logging", return_value=None), \
            patch("src.main.AptosAutoEarn._setup_signal_handlers", return_value=None):
            orchestrator = AptosAutoEarn()
        return orchestrator

    async def test_run_once_executes_all_cycles_in_order(self):
        orchestrator = self._build_orchestrator()
        events: list[str] = []

        orchestrator.run_balance_check = AsyncMock(side_effect=lambda: events.append("balance"))
        orchestrator.run_faucet_cycle = AsyncMock(side_effect=lambda: events.append("faucet"))
        orchestrator.run_activity_cycle = AsyncMock(side_effect=lambda: events.append("activity"))
        orchestrator.run_airdrop_cycle = AsyncMock(side_effect=lambda: events.append("airdrop"))

        await orchestrator.run_once()
        self.assertEqual(events, ["balance", "faucet", "activity", "airdrop"])

    async def test_shutdown_clears_schedule_and_closes_resources(self):
        orchestrator = self._build_orchestrator()
        orchestrator.db = MagicMock()
        orchestrator.wallet = MagicMock(close=AsyncMock())

        with patch("src.main.schedule.clear") as clear_mock:
            await orchestrator.shutdown()

        clear_mock.assert_called_once()
        orchestrator.db.close.assert_called_once()
        orchestrator.wallet.close.assert_awaited_once()

    def test_schedule_jobs_uses_airdrop_interval_source_of_truth(self):
        orchestrator = self._build_orchestrator()
        orchestrator.config.scheduler.airdrop_interval_hours = 12
        orchestrator.config.airdrop.check_interval_hours = 3

        calls: list[dict] = []

        def fake_every(interval: int = 1):
            return _ScheduleCall(calls, interval)

        with patch("src.main.schedule.every", side_effect=fake_every):
            orchestrator.schedule_jobs()

        airdrop_jobs = [row for row in calls if row["args"] == ("airdrop",)]
        self.assertEqual(len(airdrop_jobs), 1)
        self.assertEqual(airdrop_jobs[0]["unit"], "hours")
        self.assertEqual(airdrop_jobs[0]["interval"], 3)


if __name__ == "__main__":
    unittest.main()
