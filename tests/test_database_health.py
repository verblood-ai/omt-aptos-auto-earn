import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.database import METRICS_TABLES, MetricsDB


class TestDatabaseHealth(unittest.TestCase):
    def test_row_counts_all_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_metrics.duckdb"
            db = MetricsDB(str(path))
            counts = db.row_counts()
            self.assertEqual(set(counts.keys()), set(METRICS_TABLES))
            for name, n in counts.items():
                self.assertIsInstance(n, int, name)
                self.assertGreaterEqual(n, 0, name)
            db.close()


if __name__ == "__main__":
    unittest.main()
