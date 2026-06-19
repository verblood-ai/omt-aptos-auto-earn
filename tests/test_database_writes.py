import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.database import MetricsDB


class TestDatabaseWrites(unittest.TestCase):
    def test_insert_and_read_latest_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.duckdb"
            db = MetricsDB(str(db_path))
            try:
                db.insert_balance(network="testnet", token_symbol="APT", balance=1.5, usd_value=10.0)
                latest = db.get_latest_balance(network="testnet", token_symbol="APT")
                self.assertEqual(latest, 1.5)
            finally:
                db.close()

    def test_insert_paths_populate_metrics_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.duckdb"
            db = MetricsDB(str(db_path))
            try:
                db.insert_transaction(
                    tx_hash="0x1",
                    network="testnet",
                    tx_type="swap",
                    amount=1.0,
                    token_symbol="APT",
                    status="success",
                    fee=0.01,
                    metadata={"route": "apt-usdt"},
                )
                db.insert_faucet_claim(
                    network="testnet",
                    amount=100_000_000,
                    status="success",
                    tx_hash="0x2",
                )
                db.insert_airdrop(
                    name="Campaign One",
                    network="testnet",
                    value_estimate=0.0,
                    url="https://aptosfoundation.org/currents/campaign-one",
                )
                db.insert_activity_run(
                    module_name="dex_swap",
                    duration_seconds=2.4,
                    actions_performed=1,
                    success=True,
                )
                db.record_swap(
                    from_token="APT",
                    to_token="USDT",
                    amount_in=0.1,
                    amount_out=0.09,
                    tx_hash="0x3",
                    success=True,
                )

                counts = db.row_counts()
                self.assertEqual(counts["transactions"], 1)
                self.assertEqual(counts["faucet_claims"], 1)
                self.assertEqual(counts["airdrops_found"], 1)
                self.assertEqual(counts["activity_runs"], 1)
                self.assertEqual(counts["dex_swaps"], 1)
            finally:
                db.close()

    def test_insert_readiness_and_strategy_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metrics.duckdb"
            db = MetricsDB(str(db_path))
            try:
                db.insert_readiness_event(
                    module_name="dex_swap",
                    status="blocked",
                    reason="readiness_dex_preflight:missing",
                    source="test",
                    metadata={"signals": {"dex_preflight": {"ok": False}}},
                )
                db.insert_strategy_decision(
                    correlation_id="cid-1",
                    module_name="dex_swap",
                    mode="shadow",
                    effective_mode="shadow",
                    action="allow",
                    severity="warn",
                    reason="shadow_hypothesis:skip_budget",
                    stage="pre",
                    outcome="pending",
                    rule_hits=[{"metric": "skipped_runs", "ratio": 0.9}],
                    inputs={"balance_apt": 1.0},
                    metadata={"note": "test"},
                )
                counts = db.row_counts()
                self.assertEqual(counts["readiness_events"], 1)
                self.assertEqual(counts["strategy_decisions"], 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
