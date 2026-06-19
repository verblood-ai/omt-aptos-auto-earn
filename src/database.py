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
    "readiness_events",
    "strategy_decisions",
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
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS readiness_events_seq START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS strategy_decisions_seq START 1")

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
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0
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
                error_message VARCHAR,
                skipped BOOLEAN DEFAULT FALSE,
                skip_reason VARCHAR,
                error_class VARCHAR,
                gate_reason VARCHAR,
                retry_count INTEGER DEFAULT 0,
                metadata JSON
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

        # Readiness gate events
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS readiness_events (
                event_id BIGINT PRIMARY KEY DEFAULT nextval('readiness_events_seq'),
                timestamp TIMESTAMP,
                module_name VARCHAR,
                status VARCHAR,
                reason VARCHAR,
                source VARCHAR,
                metadata JSON
            )
        """)

        # Strategy / policy decisions
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_decisions (
                decision_id BIGINT PRIMARY KEY DEFAULT nextval('strategy_decisions_seq'),
                timestamp TIMESTAMP,
                correlation_id VARCHAR,
                module_name VARCHAR,
                mode VARCHAR,
                effective_mode VARCHAR,
                action VARCHAR,
                severity VARCHAR,
                reason VARCHAR,
                stage VARCHAR,
                outcome VARCHAR,
                rule_hits JSON,
                inputs JSON,
                metadata JSON
            )
        """)

        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Best-effort ALTER TABLE migration for legacy DB files."""
        self._ensure_column("faucet_claims", "retry_count", "INTEGER DEFAULT 0")
        self._ensure_column("activity_runs", "skipped", "BOOLEAN DEFAULT FALSE")
        self._ensure_column("activity_runs", "skip_reason", "VARCHAR")
        self._ensure_column("activity_runs", "error_class", "VARCHAR")
        self._ensure_column("activity_runs", "gate_reason", "VARCHAR")
        self._ensure_column("activity_runs", "retry_count", "INTEGER DEFAULT 0")
        self._ensure_column("activity_runs", "metadata", "JSON")

    def _ensure_column(self, table_name: str, column_name: str, column_sql: str) -> None:
        self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_sql}")

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
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ):
        """Insert a faucet claim record."""
        self.conn.execute("""
            INSERT INTO faucet_claims
            (timestamp, network, amount, status, tx_hash, error_message, retry_count)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """, [network, amount, status, tx_hash, error_message, int(retry_count)])

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
        error_message: Optional[str] = None,
        skipped: bool = False,
        skip_reason: Optional[str] = None,
        error_class: Optional[str] = None,
        gate_reason: Optional[str] = None,
        retry_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Insert an activity run record."""
        self.conn.execute("""
            INSERT INTO activity_runs
            (
                timestamp,
                module_name,
                duration_seconds,
                actions_performed,
                success,
                error_message,
                skipped,
                skip_reason,
                error_class,
                gate_reason,
                retry_count,
                metadata
            )
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            module_name,
            duration_seconds,
            actions_performed,
            success,
            error_message,
            bool(skipped),
            skip_reason,
            error_class,
            gate_reason,
            int(retry_count),
            json.dumps(metadata) if metadata is not None else None,
        ])

    def insert_readiness_event(
        self,
        module_name: str,
        status: str,
        reason: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO readiness_events
            (timestamp, module_name, status, reason, source, metadata)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
            """,
            [
                module_name,
                status,
                reason,
                source,
                json.dumps(metadata) if metadata is not None else None,
            ],
        )

    def insert_strategy_decision(
        self,
        correlation_id: str,
        module_name: str,
        mode: str,
        effective_mode: str,
        action: str,
        severity: str,
        reason: str,
        stage: str,
        outcome: str,
        rule_hits: Optional[List[Dict[str, Any]]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO strategy_decisions
            (
                timestamp,
                correlation_id,
                module_name,
                mode,
                effective_mode,
                action,
                severity,
                reason,
                stage,
                outcome,
                rule_hits,
                inputs,
                metadata
            )
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                correlation_id,
                module_name,
                mode,
                effective_mode,
                action,
                severity,
                reason,
                stage,
                outcome,
                json.dumps(rule_hits) if rule_hits is not None else None,
                json.dumps(inputs) if inputs is not None else None,
                json.dumps(metadata) if metadata is not None else None,
            ],
        )

    def get_last_faucet_success_ts(self) -> Optional[str]:
        row = self.conn.execute(
            """
            SELECT MAX(timestamp) FROM faucet_claims WHERE status = 'success'
            """
        ).fetchone()
        if not row or row[0] is None:
            return None
        value = row[0]
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        return str(value)

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
