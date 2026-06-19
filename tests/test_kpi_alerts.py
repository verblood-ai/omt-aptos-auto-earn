import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import Config, PROJECT_ROOT
from src.database import MetricsDB
from src.kpi_alerts import KPIAlertState, KPIEvaluator


class TestKPIAlerts(unittest.TestCase):
    def _cfg(self) -> Config:
        cfg = Config.load(
            config_path=str(PROJECT_ROOT / "config" / "config.yaml"),
            env_path=str(PROJECT_ROOT / ".env.example"),
        )
        cfg.kpi_alerts.enabled = True
        cfg.kpi_alerts.window_hours = 24
        cfg.kpi_alerts.cooldown_minutes = 60
        cfg.kpi_alerts.enabled_kpis = ["skip_rate", "success_rate", "retry_burst"]
        cfg.kpi_alerts.skip_rate_warn = 0.2
        cfg.kpi_alerts.skip_rate_critical = 0.4
        cfg.kpi_alerts.success_rate_warn = 0.9
        cfg.kpi_alerts.success_rate_critical = 0.7
        cfg.kpi_alerts.retry_burst_warn = 2
        cfg.kpi_alerts.retry_burst_critical = 4
        return cfg

    def test_evaluator_generates_critical_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(str(Path(tmp) / "metrics.duckdb"))
            try:
                cfg = self._cfg()
                db.insert_activity_run("dex_swap", 0.1, 0, True, skipped=True, retry_count=3)
                db.insert_activity_run("dex_swap", 0.1, 0, True, skipped=True, retry_count=2)
                snap = KPIEvaluator(cfg, db).evaluate(runtime_signals={})
                self.assertEqual(snap["severity"], "critical")
                metric_map = {m["key"]: m for m in snap["metrics"]}
                self.assertEqual(metric_map["skip_rate"]["severity"], "critical")
                self.assertEqual(metric_map["retry_burst"]["severity"], "critical")
            finally:
                db.close()

    def test_alert_state_handles_cooldown_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
            now_holder = {"value": now}

            def _now() -> datetime:
                return now_holder["value"]

            state = KPIAlertState(Path(tmp) / "kpi_state.json", cooldown_minutes=60, now_fn=_now)
            critical_snapshot = {
                "metrics": [
                    {
                        "key": "skip_rate",
                        "value": 0.6,
                        "warn_threshold": 0.2,
                        "critical_threshold": 0.4,
                        "severity": "critical",
                        "comparator": "max",
                    }
                ]
            }
            events = state.build_events(critical_snapshot)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["type"], "alert")

            events_again = state.build_events(critical_snapshot)
            self.assertEqual(events_again, [])

            now_holder["value"] = now + timedelta(minutes=61)
            events_after_cooldown = state.build_events(critical_snapshot)
            self.assertEqual(len(events_after_cooldown), 1)
            self.assertEqual(events_after_cooldown[0]["type"], "alert")

            ok_snapshot = {
                "metrics": [
                    {
                        "key": "skip_rate",
                        "value": 0.1,
                        "warn_threshold": 0.2,
                        "critical_threshold": 0.4,
                        "severity": "ok",
                        "comparator": "max",
                    }
                ]
            }
            recovery = state.build_events(ok_snapshot)
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0]["type"], "recovery")


if __name__ == "__main__":
    unittest.main()
