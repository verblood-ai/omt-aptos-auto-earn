import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.activity_dex_swap import DexSwapModule
from src.config import Config, PROJECT_ROOT


class TestDexSwapBuild(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )

    def test_build_entry_function_no_network(self):
        """Liquidswap EntryFunction builds without RPC (smoke)."""
        wallet = MagicMock()
        db = MagicMock()
        mod = DexSwapModule(self.cfg, wallet, db)
        ok, msg = mod.can_run()
        self.assertTrue(ok, msg)
        entry = mod._build_entry_function(
            mod.TOKEN_APT,
            mod.swap_to_token,
            1_000_000,
            1,
        )
        self.assertIsNotNone(entry)


if __name__ == "__main__":
    unittest.main()
