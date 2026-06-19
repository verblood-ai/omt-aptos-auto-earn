"""KPI evaluation and anti-flood alert state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


SEVERITY_ORDER = {"ok": 0, "warn": 1, "critical": 2}


@dataclass
class KPIMetricResult:
    key: str
    value: float
    warn_threshold: float
    critical_threshold: float
    severity: str
    comparator: str  # max or min
    note: str = ""


class KPIEvaluator:
    """Builds KPI snapshots from DB/runtime state."""

    def __init__(self, config: "Config", db: "MetricsDB"):
        self.config = config
        self.db = db

    def evaluate(self, runtime_signals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        runtime_signals = runtime_signals or {}
        conf = self.config.kpi_alerts
        enabled = set(conf.enabled_kpis)
        metrics: List[KPIMetricResult] = []
        counts = self._collect_activity_counts(window_hours=int(conf.window_hours))

        total_runs = counts["total_runs"]
        skipped_runs = counts["skipped_runs"]
        executed_runs = counts["executed_runs"]
        successful_runs = counts["successful_runs"]
        retry_total = counts["retry_total"]

        skip_rate = (skipped_runs / total_runs) if total_runs > 0 else 0.0
        success_rate = (successful_runs / executed_runs) if executed_runs > 0 else 1.0

        if "skip_rate" in enabled:
            metrics.append(
                self._max_threshold_metric(
                    key="skip_rate",
                    value=skip_rate,
                    warn=conf.skip_rate_warn,
                    critical=conf.skip_rate_critical,
                )
            )
        if "success_rate" in enabled:
            metrics.append(
                self._min_threshold_metric(
                    key="success_rate",
                    value=success_rate,
                    warn=conf.success_rate_warn,
                    critical=conf.success_rate_critical,
                )
            )
        if "retry_burst" in enabled:
            metrics.append(
                self._max_threshold_metric(
                    key="retry_burst",
                    value=retry_total,
                    warn=float(conf.retry_burst_warn),
                    critical=float(conf.retry_burst_critical),
                )
            )

        now = datetime.now(timezone.utc)
        faucet_gap = self._hours_since_iso(runtime_signals.get("last_faucet_success_ts"), now)
        if "faucet_claim_gap" in enabled and faucet_gap is not None:
            metrics.append(
                self._max_threshold_metric(
                    key="faucet_claim_gap",
                    value=faucet_gap,
                    warn=float(conf.faucet_claim_gap_warn_hours),
                    critical=float(conf.faucet_claim_gap_critical_hours),
                )
            )
        airdrop_gap = self._hours_since_iso(runtime_signals.get("last_airdrop_check_ts"), now)
        if "airdrop_check_staleness" in enabled and airdrop_gap is not None:
            metrics.append(
                self._max_threshold_metric(
                    key="airdrop_check_staleness",
                    value=airdrop_gap,
                    warn=float(conf.airdrop_check_staleness_warn_hours),
                    critical=float(conf.airdrop_check_staleness_critical_hours),
                )
            )

        worst = "ok"
        for metric in metrics:
            if SEVERITY_ORDER[metric.severity] > SEVERITY_ORDER[worst]:
                worst = metric.severity

        return {
            "timestamp": now.isoformat(),
            "window_hours": int(conf.window_hours),
            "severity": worst,
            "counts": counts,
            "metrics": [
                {
                    "key": m.key,
                    "value": m.value,
                    "warn_threshold": m.warn_threshold,
                    "critical_threshold": m.critical_threshold,
                    "severity": m.severity,
                    "comparator": m.comparator,
                    "note": m.note,
                }
                for m in metrics
            ],
        }

    def _collect_activity_counts(self, *, window_hours: int) -> Dict[str, float]:
        row = self.db.conn.execute(
            """
            SELECT
                COUNT(*)::DOUBLE AS total_runs,
                SUM(CASE WHEN skipped THEN 1 ELSE 0 END)::DOUBLE AS skipped_runs,
                SUM(CASE WHEN NOT skipped THEN 1 ELSE 0 END)::DOUBLE AS executed_runs,
                SUM(CASE WHEN NOT skipped AND success THEN 1 ELSE 0 END)::DOUBLE AS successful_runs,
                COALESCE(SUM(COALESCE(retry_count, 0)), 0)::DOUBLE AS retry_total
            FROM activity_runs
            WHERE timestamp >= CURRENT_TIMESTAMP - (? * INTERVAL '1 hour')
            """,
            [window_hours],
        ).fetchone()
        if not row:
            return {
                "total_runs": 0.0,
                "skipped_runs": 0.0,
                "executed_runs": 0.0,
                "successful_runs": 0.0,
                "retry_total": 0.0,
            }
        return {
            "total_runs": float(row[0] or 0.0),
            "skipped_runs": float(row[1] or 0.0),
            "executed_runs": float(row[2] or 0.0),
            "successful_runs": float(row[3] or 0.0),
            "retry_total": float(row[4] or 0.0),
        }

    @staticmethod
    def _hours_since_iso(value: Optional[str], now: datetime) -> Optional[float]:
        if not value:
            return None
        try:
            ts = datetime.fromisoformat(value)
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = now - ts.astimezone(timezone.utc)
        return delta.total_seconds() / 3600.0

    @staticmethod
    def _max_threshold_metric(*, key: str, value: float, warn: float, critical: float) -> KPIMetricResult:
        severity = "ok"
        if value >= critical:
            severity = "critical"
        elif value >= warn:
            severity = "warn"
        return KPIMetricResult(
            key=key,
            value=float(value),
            warn_threshold=float(warn),
            critical_threshold=float(critical),
            severity=severity,
            comparator="max",
        )

    @staticmethod
    def _min_threshold_metric(*, key: str, value: float, warn: float, critical: float) -> KPIMetricResult:
        severity = "ok"
        if value <= critical:
            severity = "critical"
        elif value <= warn:
            severity = "warn"
        return KPIMetricResult(
            key=key,
            value=float(value),
            warn_threshold=float(warn),
            critical_threshold=float(critical),
            severity=severity,
            comparator="min",
        )


class KPIAlertState:
    """Persists anti-flood state for KPI notifications."""

    def __init__(
        self,
        state_path: Path,
        cooldown_minutes: int,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.state_path = state_path
        self.cooldown = timedelta(minutes=max(1, int(cooldown_minutes)))
        self.now_fn = now_fn
        self.state = self._load_state()

    def build_events(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        now = self.now_fn()
        current_map = {metric["key"]: metric for metric in snapshot.get("metrics", [])}

        for key, metric in current_map.items():
            new_severity = metric.get("severity", "ok")
            prev = self.state.get(key, {})
            prev_severity = prev.get("severity", "ok")
            last_sent = self._parse_iso(prev.get("last_sent_at"))

            if new_severity in {"warn", "critical"}:
                should_send = new_severity != prev_severity
                if not should_send and last_sent is not None:
                    should_send = (now - last_sent) >= self.cooldown
                if should_send:
                    events.append({"type": "alert", "key": key, "metric": metric})
                    self.state[key] = {"severity": new_severity, "last_sent_at": now.isoformat()}
                else:
                    self.state[key] = {"severity": new_severity, "last_sent_at": prev.get("last_sent_at")}
            else:
                if prev_severity in {"warn", "critical"}:
                    events.append({"type": "recovery", "key": key, "metric": metric, "previous": prev_severity})
                    self.state[key] = {"severity": "ok", "last_sent_at": now.isoformat()}
                else:
                    self.state[key] = {"severity": "ok", "last_sent_at": prev.get("last_sent_at")}

        self._save_state()
        return events

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, indent=2)

    @staticmethod
    def _parse_iso(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
