import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.airdrop_monitor import parse_aptos_currents_html


class TestAirdropParse(unittest.TestCase):
    def test_parse_currents_html_fixture(self):
        html = """
        <html><body>
        <a href="/currents/some-testnet-airdrop-campaign">x</a>
        <a href="https://other.example/foo">skip</a>
        </body></html>
        """
        base = "https://aptosfoundation.org/currents"
        rows = parse_aptos_currents_html(html, base, "devnet")
        self.assertTrue(len(rows) >= 1)
        self.assertTrue(all("aptosfoundation.org/currents/" in r["url"].lower() for r in rows))
        self.assertEqual(rows[0]["network"], "devnet")


if __name__ == "__main__":
    unittest.main()
