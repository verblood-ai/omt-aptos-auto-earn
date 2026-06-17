import os
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.activity_lending import LendingModule
from src.activity_nft_mint import NFTMintModule


class TestActivityStubs(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )

    def test_stubs_disabled_by_default(self):
        self.assertFalse(self.cfg.activity.allow_stubs)

        lending = LendingModule(self.cfg, None, None)  # wallet/db unused by can_run()
        nft = NFTMintModule(self.cfg, None, None)

        can_lend, _ = lending.can_run()
        can_nft, _ = nft.can_run()
        self.assertFalse(can_lend)
        self.assertFalse(can_nft)


if __name__ == "__main__":
    unittest.main()
