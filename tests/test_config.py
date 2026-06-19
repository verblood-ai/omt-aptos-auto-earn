import os
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT


class TestConfig(unittest.TestCase):
    def test_project_root_points_at_repo(self):
        self.assertTrue((PROJECT_ROOT / "run.py").exists())

    def test_load_resolves_relative_paths(self):
        # Ensure config loads even when cwd is not the repo root.
        prev_cwd = os.getcwd()
        try:
            os.chdir(str(Path.home()))
            cfg = Config.load(
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                env_path=str(PROJECT_ROOT / ".env.example"),
            )
            self.assertTrue(cfg.node_url.startswith("http"))
            self.assertTrue(cfg.faucet.api_url.startswith("http"))
            self.assertTrue(str(cfg.metrics.db_path).startswith(str(PROJECT_ROOT)))
        finally:
            os.chdir(prev_cwd)

    def test_scheduler_faucet_time_env_override(self):
        prev = os.environ.get("SCHEDULER_FAUCET_DAILY_AT")
        os.environ["SCHEDULER_FAUCET_DAILY_AT"] = "11:45"
        try:
            cfg = Config.load(
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                env_path=str(PROJECT_ROOT / ".env.example"),
            )
            self.assertEqual(cfg.scheduler.faucet_daily_at, "11:45")
        finally:
            if prev is None:
                os.environ.pop("SCHEDULER_FAUCET_DAILY_AT", None)
            else:
                os.environ["SCHEDULER_FAUCET_DAILY_AT"] = prev

    def test_faucet_amount_is_loaded_as_octas(self):
        prev = os.environ.get("FAUCET_AMOUNT")
        os.environ["FAUCET_AMOUNT"] = "250000000"
        try:
            cfg = Config.load(
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                env_path=str(PROJECT_ROOT / ".env.example"),
            )
            self.assertEqual(cfg.faucet.amount, 250_000_000)
            self.assertIsInstance(cfg.faucet.amount, int)
        finally:
            if prev is None:
                os.environ.pop("FAUCET_AMOUNT", None)
            else:
                os.environ["FAUCET_AMOUNT"] = prev

    def test_airdrop_interval_is_single_source_of_truth(self):
        prev_air = os.environ.get("AIRDROP_CHECK_INTERVAL_HOURS")
        prev_sch = os.environ.get("SCHEDULER_AIRDROP_INTERVAL_HOURS")
        os.environ["AIRDROP_CHECK_INTERVAL_HOURS"] = "4"
        os.environ["SCHEDULER_AIRDROP_INTERVAL_HOURS"] = "9"
        try:
            cfg = Config.load(
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                env_path=str(PROJECT_ROOT / ".env.does-not-exist"),
            )
            self.assertEqual(cfg.airdrop.check_interval_hours, 4)
            self.assertEqual(cfg.scheduler.airdrop_interval_hours, 4)
        finally:
            if prev_air is None:
                os.environ.pop("AIRDROP_CHECK_INTERVAL_HOURS", None)
            else:
                os.environ["AIRDROP_CHECK_INTERVAL_HOURS"] = prev_air
            if prev_sch is None:
                os.environ.pop("SCHEDULER_AIRDROP_INTERVAL_HOURS", None)
            else:
                os.environ["SCHEDULER_AIRDROP_INTERVAL_HOURS"] = prev_sch

    def test_readiness_and_strategy_env_overrides(self):
        prev_mode = os.environ.get("STRATEGY_MODE")
        prev_enabled = os.environ.get("STRATEGY_ENABLED")
        prev_checks = os.environ.get("READINESS_MANDATORY_CHECKS")
        os.environ["STRATEGY_ENABLED"] = "true"
        os.environ["STRATEGY_MODE"] = "advisory"
        os.environ["READINESS_MANDATORY_CHECKS"] = "rpc_health,min_balance_guard"
        try:
            cfg = Config.load(
                config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                env_path=str(PROJECT_ROOT / ".env.does-not-exist"),
            )
            self.assertTrue(cfg.strategy.enabled)
            self.assertEqual(cfg.strategy.mode, "advisory")
            self.assertEqual(cfg.readiness.mandatory_checks, ["rpc_health", "min_balance_guard"])
        finally:
            if prev_mode is None:
                os.environ.pop("STRATEGY_MODE", None)
            else:
                os.environ["STRATEGY_MODE"] = prev_mode
            if prev_enabled is None:
                os.environ.pop("STRATEGY_ENABLED", None)
            else:
                os.environ["STRATEGY_ENABLED"] = prev_enabled
            if prev_checks is None:
                os.environ.pop("READINESS_MANDATORY_CHECKS", None)
            else:
                os.environ["READINESS_MANDATORY_CHECKS"] = prev_checks

    def test_invalid_readiness_mode_raises(self):
        prev = os.environ.get("READINESS_FAIL_MODE")
        os.environ["READINESS_FAIL_MODE"] = "invalid"
        try:
            with self.assertRaises(ValueError):
                Config.load(
                    config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
                    env_path=str(PROJECT_ROOT / ".env.does-not-exist"),
                )
        finally:
            if prev is None:
                os.environ.pop("READINESS_FAIL_MODE", None)
            else:
                os.environ["READINESS_FAIL_MODE"] = prev


if __name__ == "__main__":
    unittest.main()
