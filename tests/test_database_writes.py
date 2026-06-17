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


if __name__ == "__main__":
    unittest.main()
