import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.activity_dex_swap import (
    DexSwapModule,
    classify_swap_error,
    is_network_exception,
    parse_deposit_amount_for_coin,
)
from src.config import Config, PROJECT_ROOT


def _deposit_event(coin_type: str, amount: int) -> dict:
    return {
        "type": f"0x1::coin::DepositEvent<{coin_type}>",
        "data": {"amount": str(amount)},
    }


class TestDexSwapHelpers(unittest.TestCase):
    def test_classify_linker(self):
        self.assertEqual(
            classify_swap_error("Linker Error: Module 0xabc::m doesn't exist"),
            "linker",
        )

    def test_classify_slippage(self):
        self.assertEqual(classify_swap_error("ABORTED below minimum output"), "slippage")

    def test_parse_deposit(self):
        usdt = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9::coins::USDT"
        evs = [_deposit_event(usdt, 42_000)]
        self.assertEqual(parse_deposit_amount_for_coin(evs, usdt), 42_000)

    def test_is_network_exception(self):
        self.assertTrue(is_network_exception(httpx.TimeoutException("x")))
        self.assertFalse(is_network_exception(ValueError("linker bad")))


class TestDexSwapRun(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        self.wallet = MagicMock()
        self.db = MagicMock()

    async def test_success_path_records_committed_out(self):
        mod = DexSwapModule(self.cfg, self.wallet, self.db)
        usdt = mod.swap_to_token

        self.wallet.get_balance = AsyncMock(return_value=10.0)

        sim_probe = {"success": True, "events": [_deposit_event(usdt, 50_000)]}
        sim_final = {"success": True, "events": [_deposit_event(usdt, 49_500)]}
        self.wallet.simulate_transaction = AsyncMock(
            side_effect=[
                (True, [sim_probe], ""),
                (True, [sim_final], ""),
            ]
        )
        self.wallet.submit_transaction = AsyncMock(return_value="0xdeadbeef")
        self.wallet.wait_for_transaction = AsyncMock(return_value=True)
        self.wallet.get_transaction_details = AsyncMock(
            return_value={"events": [_deposit_event(usdt, 49_000)]}
        )

        result = await mod.run()
        self.assertTrue(result["success"])
        self.assertEqual(result["actions"], 1)
        self.assertEqual(result["amount_out_actual"], 49_000)
        self.wallet.submit_transaction.assert_awaited_once()
        self.db.record_swap.assert_called_once()
        args, kwargs = self.db.record_swap.call_args
        self.assertEqual(kwargs.get("amount_out"), 49_000.0)

    async def test_probe_linker_no_submit(self):
        mod = DexSwapModule(self.cfg, self.wallet, self.db)
        self.wallet.get_balance = AsyncMock(return_value=10.0)
        self.wallet.simulate_transaction = AsyncMock(
            return_value=(
                False,
                [{"vm_status": "Linker Error: Module x::scripts_v2 doesn't exist"}],
                "Linker Error: Module x::scripts_v2 doesn't exist",
            )
        )

        result = await mod.run()
        self.assertFalse(result["success"])
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("error_class"), "linker")
        self.wallet.submit_transaction.assert_not_called()

    async def test_simulate_retries_on_timeout(self):
        mod = DexSwapModule(self.cfg, self.wallet, self.db)
        usdt = mod.swap_to_token
        ok_body = {"success": True, "events": [_deposit_event(usdt, 10_000)]}

        self.wallet.get_balance = AsyncMock(return_value=10.0)
        self.wallet.simulate_transaction = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("timeout"),
                (True, [ok_body], ""),
                (True, [ok_body], ""),
            ]
        )
        self.wallet.submit_transaction = AsyncMock(return_value="0xabc")
        self.wallet.wait_for_transaction = AsyncMock(return_value=True)
        self.wallet.get_transaction_details = AsyncMock(return_value={"events": [_deposit_event(usdt, 9_900)]})

        with patch("src.activity_dex_swap.asyncio.sleep", new_callable=AsyncMock):
            result = await mod.run()

        self.assertTrue(result["success"])
        self.assertEqual(self.wallet.simulate_transaction.await_count, 3)


if __name__ == "__main__":
    unittest.main()
