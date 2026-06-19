import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.policy_engine import PolicyOutcome
from src.strategy_engine import StrategyEngine


class _StubPolicyEngine:
    def __init__(self, outcome: PolicyOutcome):
        self._outcome = outcome

    def evaluate(self, module_name: str) -> PolicyOutcome:
        _ = module_name
        return self._outcome


class TestStrategyEngine(unittest.TestCase):
    def _cfg(self, mode: str, enabled: bool = True) -> Config:
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        cfg.strategy.enabled = enabled
        cfg.strategy.mode = mode
        return cfg

    def test_shadow_mode_never_blocks(self):
        cfg = self._cfg("shadow", enabled=True)
        policy = PolicyOutcome(action="block", severity="critical", reason="skip_budget_exhausted")
        decision = StrategyEngine(cfg, _StubPolicyEngine(policy)).evaluate({"module_name": "dex_swap"})
        self.assertEqual(decision.action, "allow")
        self.assertTrue(decision.advisory_notice)
        self.assertIn("shadow_hypothesis", decision.reason)

    def test_advisory_mode_warns_without_blocking(self):
        cfg = self._cfg("advisory", enabled=True)
        policy = PolicyOutcome(action="block", severity="critical", reason="retry_budget_exhausted")
        decision = StrategyEngine(cfg, _StubPolicyEngine(policy)).evaluate({"module_name": "dex_swap"})
        self.assertEqual(decision.action, "warn")
        self.assertTrue(decision.advisory_notice)

    def test_enforcement_mode_blocks(self):
        cfg = self._cfg("enforcement", enabled=True)
        policy = PolicyOutcome(action="block", severity="critical", reason="failed_runs_budget_exhausted")
        decision = StrategyEngine(cfg, _StubPolicyEngine(policy)).evaluate({"module_name": "dex_swap"})
        self.assertEqual(decision.action, "block")
        self.assertIn("enforcement_block", decision.reason)

    def test_disabled_strategy_is_allow(self):
        cfg = self._cfg("enforcement", enabled=False)
        policy = PolicyOutcome(action="block", severity="critical", reason="ignored")
        decision = StrategyEngine(cfg, _StubPolicyEngine(policy)).evaluate({"module_name": "dex_swap"})
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason, "strategy_disabled")


if __name__ == "__main__":
    unittest.main()
