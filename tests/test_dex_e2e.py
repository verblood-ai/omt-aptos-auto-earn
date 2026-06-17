"""
Optional on-network smoke for DEX (run with APTOS_E2E=1 and a funded test wallet).

Not enabled in CI by default.
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


@unittest.skipUnless(os.environ.get("APTOS_E2E") == "1", "set APTOS_E2E=1 to run on-chain DEX smoke")
class TestDexE2E(unittest.IsolatedAsyncioTestCase):
    async def test_module_check_live(self):
        from src.config import Config, PROJECT_ROOT
        from src.dex_diagnostics import run_module_check

        env_file = PROJECT_ROOT / ".env"
        if not env_file.exists():
            env_file = PROJECT_ROOT / ".env.example"
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(env_file),
        )
        code = await run_module_check(cfg, ("scripts_v2", "router_v2"))
        self.assertEqual(code, 0, "Liquidswap modules must be published at contracts.liquidswap_router")


if __name__ == "__main__":
    unittest.main()
