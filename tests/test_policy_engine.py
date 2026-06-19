import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.database import MetricsDB
from src.policy_engine import PolicyEngine


class TestPolicyEngine(unittest.TestCase):
    def _build_cfg(self) -> Config:
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        cfg.strategy.enabled = True
        cfg.strategy.mode = "enforcement"
        cfg.strategy.policy.window_hours = 24
        cfg.strategy.policy.skip_budget = 2
        cfg.strategy.policy.retry_budget = 5
        cfg.strategy.policy.failed_runs_budget = 2
        cfg.strategy.policy.execution_budget = 20
        cfg.strategy.policy.advisory_ratio = 0.8
        return cfg

    def test_block_when_skip_budget_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(str(Path(tmp) / "metrics.duckdb"))
            try:
                cfg = self._build_cfg()
                for _ in range(3):
                    db.insert_activity_run(
                        module_name="dex_swap",
                        duration_seconds=0.1,
                        actions_performed=0,
                        success=True,
                        skipped=True,
                        skip_reason="readiness_blocked",
                    )
                outcome = PolicyEngine(cfg, db).evaluate("dex_swap")
                self.assertEqual(outcome.action, "block")
                self.assertEqual(outcome.severity, "critical")
            finally:
                db.close()

    def test_warn_when_budget_near_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(str(Path(tmp) / "metrics.duckdb"))
            try:
                cfg = self._build_cfg()
                db.insert_activity_run(
                    module_name="dex_swap",
                    duration_seconds=0.1,
                    actions_performed=1,
                    success=True,
                    skipped=False,
                    retry_count=4,
                )
                outcome = PolicyEngine(cfg, db).evaluate("dex_swap")
                self.assertIn(outcome.action, {"warn", "allow"})
                self.assertTrue(any(hit.metric == "retry_total" for hit in outcome.rule_hits))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
