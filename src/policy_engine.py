"""Policy threshold/budget evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ACTION_PRIORITY = {"allow": 0, "warn": 1, "defer": 2, "block": 3}


@dataclass
class PolicyRuleHit:
    metric: str
    value: float
    budget: float
    ratio: float
    severity: str
    action: str
    reason: str


@dataclass
class PolicyOutcome:
    action: str = "allow"
    severity: str = "ok"
    reason: str = "policy_ok"
    rule_hits: List[PolicyRuleHit] = field(default_factory=list)
    budget_snapshot: Dict[str, Dict[str, float]] = field(default_factory=dict)
    metrics_snapshot: Dict[str, float] = field(default_factory=dict)
    error: str = ""


class PolicyEngine:
    """Evaluates policy budgets using metrics from DuckDB."""

    def __init__(self, config: "Config", db: "MetricsDB"):
        self.config = config
        self.db = db

    def evaluate(self, module_name: str) -> PolicyOutcome:
        if not self.config.strategy.enabled:
            return PolicyOutcome(action="allow", severity="ok", reason="strategy_disabled")
        if not self.config.strategy.policy.enabled:
            return PolicyOutcome(action="allow", severity="ok", reason="policy_disabled")

        try:
            metrics = self._collect_metrics(module_name=module_name)
            budgets = self._resolve_budgets(module_name=module_name)
            return self._apply_rules(metrics=metrics, budgets=budgets)
        except Exception as exc:  # noqa: BLE001
            return PolicyOutcome(
                action="block",
                severity="critical",
                reason="policy_eval_error",
                error=str(exc),
            )

    def _collect_metrics(self, module_name: str) -> Dict[str, float]:
        window_hours = int(self.config.strategy.policy.window_hours)
        params = [window_hours, module_name]
        row = self.db.conn.execute(
            """
            SELECT
                COUNT(*)::DOUBLE AS total_runs,
                SUM(CASE WHEN skipped THEN 1 ELSE 0 END)::DOUBLE AS skipped_runs,
                SUM(CASE WHEN NOT skipped AND NOT success THEN 1 ELSE 0 END)::DOUBLE AS failed_runs,
                SUM(CASE WHEN NOT skipped THEN 1 ELSE 0 END)::DOUBLE AS executed_runs,
                COALESCE(SUM(COALESCE(retry_count, 0)), 0)::DOUBLE AS retry_total
            FROM activity_runs
            WHERE timestamp >= CURRENT_TIMESTAMP - (? * INTERVAL '1 hour')
              AND module_name = ?
            """,
            params,
        ).fetchone()

        if not row:
            return {
                "total_runs": 0.0,
                "skipped_runs": 0.0,
                "failed_runs": 0.0,
                "executed_runs": 0.0,
                "retry_total": 0.0,
            }
        return {
            "total_runs": float(row[0] or 0.0),
            "skipped_runs": float(row[1] or 0.0),
            "failed_runs": float(row[2] or 0.0),
            "executed_runs": float(row[3] or 0.0),
            "retry_total": float(row[4] or 0.0),
        }

    def _resolve_budgets(self, module_name: str) -> Dict[str, float]:
        policy = self.config.strategy.policy
        budgets = {
            "skipped_runs": float(policy.skip_budget),
            "retry_total": float(policy.retry_budget),
            "failed_runs": float(policy.failed_runs_budget),
            "executed_runs": float(policy.execution_budget),
        }
        override = policy.module_overrides.get(module_name)
        if override:
            if override.skip_budget is not None:
                budgets["skipped_runs"] = float(override.skip_budget)
            if override.retry_budget is not None:
                budgets["retry_total"] = float(override.retry_budget)
            if override.failed_runs_budget is not None:
                budgets["failed_runs"] = float(override.failed_runs_budget)
            if override.execution_budget is not None:
                budgets["executed_runs"] = float(override.execution_budget)
        return budgets

    def _apply_rules(self, *, metrics: Dict[str, float], budgets: Dict[str, float]) -> PolicyOutcome:
        policy = self.config.strategy.policy
        outcome = PolicyOutcome(
            action="allow",
            severity="ok",
            reason="policy_ok",
            budget_snapshot={
                key: {"value": metrics.get(key, 0.0), "budget": budgets.get(key, 0.0)}
                for key in budgets.keys()
            },
            metrics_snapshot=dict(metrics),
        )

        advisory_ratio = float(policy.advisory_ratio)
        warning_ratios = [float(v) for v in policy.warning_ratios]
        for metric, budget in budgets.items():
            value = float(metrics.get(metric, 0.0))
            ratio = 0.0 if budget <= 0 else value / budget
            if budget <= 0 and value > 0:
                ratio = 1.0

            if ratio >= 1.0:
                hit = PolicyRuleHit(
                    metric=metric,
                    value=value,
                    budget=budget,
                    ratio=ratio,
                    severity="critical",
                    action="block",
                    reason=f"{metric}_budget_exhausted",
                )
                outcome.rule_hits.append(hit)
                self._upgrade_outcome(outcome, action="block", severity="critical", reason=hit.reason)
                continue

            if ratio >= advisory_ratio:
                hit = PolicyRuleHit(
                    metric=metric,
                    value=value,
                    budget=budget,
                    ratio=ratio,
                    severity="warn",
                    action="warn",
                    reason=f"{metric}_budget_near_limit",
                )
                outcome.rule_hits.append(hit)
                self._upgrade_outcome(outcome, action="warn", severity="warn", reason=hit.reason)
                continue

            for threshold in warning_ratios:
                if ratio >= threshold:
                    hit = PolicyRuleHit(
                        metric=metric,
                        value=value,
                        budget=budget,
                        ratio=ratio,
                        severity="warn",
                        action="warn",
                        reason=f"{metric}_burn_rate_{int(threshold * 100)}",
                    )
                    outcome.rule_hits.append(hit)
                    self._upgrade_outcome(outcome, action="warn", severity="warn", reason=hit.reason)
                    break

        return outcome

    @staticmethod
    def _upgrade_outcome(outcome: PolicyOutcome, *, action: str, severity: str, reason: str) -> None:
        if ACTION_PRIORITY.get(action, 0) > ACTION_PRIORITY.get(outcome.action, 0):
            outcome.action = action
            outcome.severity = severity
            outcome.reason = reason
