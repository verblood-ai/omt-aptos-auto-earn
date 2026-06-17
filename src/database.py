"""Metrics database handler using DuckDB.

Logical tables (created in _create_tables): balance_history, transactions,
faucet_claims, airdrops_found, activity_runs, dex_swaps. Column definitions
live in the SQL DDL inside this module.
"""

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

METRICS_TABLES: tuple[str, ...] = (
    "balance_history",
    "transactions",
    "faucet_claims",
    "airdrops_found",
    "activity_runs",
    "dex_swaps",
)


class MetricsDB:
    """Handles all metrics storage and retrieval."""

    def __init__(self, db_path: str = "data/metrics.duckdb"):
        """Initialize database connection and create tables if needed."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._create_tables()

    def row_counts(self) -> Dict[str, int]:
        """Return ``COUNT(*)`` for each metrics table (operations health check)."""
        counts: Dict[str, int] = {}
        for name in METRICS_TABLES:
            row = self.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
            counts[name] = int(row[0]) if row else 0
        return counts

    def _create_tables(self):
        """Create all required tables."""
        # Create sequences for auto-increment
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS faucet_claims_seq START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS airdrops_found_seq START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS activity_runs_seq START 1")

        # Balance history
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_history (
                timestamp TIMESTAMP,
                network VARCHAR,
                token_symbol VARCHAR,
                balance DOUBLE,
                usd_value DOUBLE
            )
        """)

        # Transactions
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                tx_hash VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP,
                network VARCHAR,
                type VARCHAR,
                amount DOUBLE,
                token_symbol VARCHAR,
                status VARCHAR,
                fee DOUBLE,
                metadata JSON
            )
        """)

        # Faucet claims
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS faucet_claims (
                claim_id BIGINT PRIMARY KEY DEFAULT nextval('faucet_claims_seq'),
                timestamp TIMESTAMP,
                network VARCHAR,
                amount DOUBLE,
                status VARCHAR,
                tx_hash VARCHAR,
                error_message VARCHAR
            )
        """)

        # Airdrops found
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS airdrops_found (
                airdrop_id INTEGER PRIMARY KEY DEFAULT nextval('airdrops_found_seq'),
                timestamp TIMESTAMP,
                name VARCHAR,
                network VARCHAR,
                value_estimate DOUBLE,
                url VARCHAR,
                status VARCHAR DEFAULT 'pending'
            )
        """)

        # Activity runs
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_runs (
                run_id INTEGER PRIMARY KEY DEFAULT nextval('activity_runs_seq'),
                timestamp TIMESTAMP,
                module_name VARCHAR,
                duration_seconds DOUBLE,
                actions_performed INTEGER,
                success BOOLEAN,
                error_message VARCHAR
            )
        """)

        # DEX swap history
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS dex_swaps (
                timestamp TIMESTAMP,
                tx_hash VARCHAR,
                from_token VARCHAR,
                to_token VARCHAR,
                amount_in DOUBLE,
                amount_out DOUBLE,
                success BOOLEAN
            )
        """)

    def insert_balance(self, network: str, token_symbol: str, balance: float, usd_value: Optional[float] = None):
        """Insert a balance snapshot."""
        self.conn.execute("""
            INSERT INTO balance_history (timestamp, network, token_symbol, balance, usd_value)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?)
        """, [network, token_symbol, balance, usd_value])

    def insert_transaction(
        self,
        tx_hash: str,
        network: str,
        tx_type: str,
        amount: float,
        token_symbol: str,
        status: str,
        fee: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Insert a transaction record.

        ``metadata`` is stored as valid JSON text in the DuckDB ``JSON`` column.
        Query with DuckDB JSON helpers, for example ``json_extract`` / casts.
        """
        self.conn.execute("""
            INSERT OR REPLACE INTO transactions
            (tx_hash, timestamp, network, type, amount, token_symbol, status, fee, metadata)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
        """, [tx_hash, network, tx_type, amount, token_symbol, status, fee, json.dumps(metadata) if metadata is not None else None])

    def insert_faucet_claim(
        self,
        network: str,
        amount: float,
        status: str,
        tx_hash: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Insert a faucet claim record."""
        self.conn.execute("""
            INSERT INTO faucet_claims
            (timestamp, network, amount, status, tx_hash, error_message)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
        """, [network, amount, status, tx_hash, error_message])

    def insert_airdrop(
        self,
        name: str,
        network: str,
        value_estimate: float,
        url: str,
        status: str = "pending"
    ):
        """Insert a found airdrop."""
        self.conn.execute("""
            INSERT INTO airdrops_found
            (timestamp, name, network, value_estimate, url, status)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
        """, [name, network, value_estimate, url, status])

    def insert_activity_run(
        self,
        module_name: str,
        duration_seconds: float,
        actions_performed: int,
        success: bool,
        error_message: Optional[str] = None
    ):
        """Insert an activity run record."""
        self.conn.execute("""
            INSERT INTO activity_runs
            (timestamp, module_name, duration_seconds, actions_performed, success, error_message)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
        """, [module_name, duration_seconds, actions_performed, success, error_message])

    def record_swap(
        self,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float,
        tx_hash: str,
        success: bool,
    ):
        """Persist a swap-specific metric alongside the generic transactions table."""
        self.conn.execute("""
            INSERT INTO dex_swaps
            (timestamp, tx_hash, from_token, to_token, amount_in, amount_out, success)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """, [tx_hash, from_token, to_token, amount_in, amount_out, success])

    def get_latest_balance(self, network: str, token_symbol: str) -> Optional[float]:
        """Get the most recent balance for a network/token."""
        result = self.conn.execute("""
            SELECT balance FROM balance_history
            WHERE network = ? AND token_symbol = ?
            ORDER BY timestamp DESC LIMIT 1
        """, [network, token_symbol]).fetchone()
        return result[0] if result else None

    def get_balance_history(self, network: str, token_symbol: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Get balance history for the last N hours."""
        results = self.conn.execute("""
            SELECT timestamp, balance, usd_value
            FROM balance_history
            WHERE network = ? AND token_symbol = ?
                AND timestamp >= CURRENT_TIMESTAMP - INTERVAL ? HOUR
            ORDER BY timestamp ASC
        """, [network, token_symbol, hours]).fetchall()
        return [
            {"timestamp": row[0], "balance": row[1], "usd_value": row[2]}
            for row in results
        ]

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get aggregated statistics."""
        stats = {}

        # Total faucet claims
        result = self.conn.execute("""
            SELECT COUNT(*), SUM(amount)
            FROM faucet_claims
            WHERE timestamp >= CURRENT_TIMESTAMP - INTERVAL ? DAY
        """, [days]).fetchone()
        stats["faucet_claims_count"] = result[0] or 0
        stats["faucet_claims_total"] = result[1] or 0.0

        # Successful airdrops
        result = self.conn.execute("""
            SELECT COUNT(*), SUM(value_estimate)
            FROM airdrops_found
            WHERE status = 'claimed' AND timestamp >= CURRENT_TIMESTAMP - INTERVAL ? DAY
        """, [days]).fetchone()
        stats["airdrops_claimed"] = result[0] or 0
        stats["airdrops_value"] = result[1] or 0.0

        # Activity success rate
        result = self.conn.execute("""
            SELECT COUNT(*), AVG(duration_seconds)
            FROM activity_runs
            WHERE timestamp >= CURRENT_TIMESTAMP - INTERVAL ? DAY
        """, [days]).fetchone()
        stats["activity_runs"] = result[0] or 0
        stats["avg_activity_duration"] = result[1] or 0.0

        return stats

    def close(self):
        """Close database connection."""
        self.conn.close()
