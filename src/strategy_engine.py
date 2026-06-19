"""Strategy engine modes: shadow -> advisory -> enforcement."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .policy_engine import PolicyEngine, PolicyOutcome, PolicyRuleHit


@dataclass
class StrategyDecision:
    mode: str
    effective_mode: str
    action: str
    reason: str
    severity: str = "ok"
    advisory_notice: bool = False
    executed_despite_advisory: bool = False
    remediation_hint: str = ""
    rule_hits: List[Dict[str, Any]] = field(default_factory=list)
    policy_snapshot: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class StrategyEngine:
    """Mode-aware decision point for each activity module run."""

    def __init__(self, config: "Config", policy_engine: PolicyEngine):
        self.config = config
        self.policy_engine = policy_engine

    def evaluate(self, context: Dict[str, Any]) -> StrategyDecision:
        mode = self._configured_mode()
        effective_mode = self._effective_mode(mode)

        if not self.config.strategy.enabled:
            return StrategyDecision(
                mode=mode,
                effective_mode="shadow",
                action="allow",
                reason="strategy_disabled",
                metadata={"module_name": context.get("module_name", "")},
            )

        policy_outcome = self.policy_engine.evaluate(module_name=context.get("module_name", "unknown"))
        decision = self._decision_from_policy(
            mode=mode,
            effective_mode=effective_mode,
            policy_outcome=policy_outcome,
            context=context,
        )
        return decision

    def _decision_from_policy(
        self,
        *,
        mode: str,
        effective_mode: str,
        policy_outcome: PolicyOutcome,
        context: Dict[str, Any],
    ) -> StrategyDecision:
        reason = policy_outcome.reason
        advisory_notice = False
        action = "allow"
        severity = policy_outcome.severity

        if effective_mode == "shadow":
            action = "allow"
            if policy_outcome.action in {"warn", "block", "defer"}:
                advisory_notice = True
                reason = f"shadow_hypothesis:{policy_outcome.reason}"
        elif effective_mode == "advisory":
            if policy_outcome.action in {"warn", "block", "defer"}:
                action = "warn"
                advisory_notice = True
                reason = f"advisory:{policy_outcome.reason}"
            else:
                action = "allow"
        else:  # enforcement
            action = policy_outcome.action
            if action == "warn":
                advisory_notice = True
                reason = f"enforcement_warning:{policy_outcome.reason}"
            elif action == "block":
                reason = f"enforcement_block:{policy_outcome.reason}"

        if action == "block":
            remediation_hint = "Decrease load or raise policy budgets after KPI review."
        elif action == "warn":
            remediation_hint = "Investigate burn-rate and consider temporary advisory mode."
        else:
            remediation_hint = ""

        return StrategyDecision(
            mode=mode,
            effective_mode=effective_mode,
            action=action,
            reason=reason,
            severity=severity,
            advisory_notice=advisory_notice,
            remediation_hint=remediation_hint,
            rule_hits=[asdict(hit) if isinstance(hit, PolicyRuleHit) else dict(hit) for hit in policy_outcome.rule_hits],
            policy_snapshot={
                "budget_snapshot": policy_outcome.budget_snapshot,
                "metrics_snapshot": policy_outcome.metrics_snapshot,
                "policy_action": policy_outcome.action,
                "policy_severity": policy_outcome.severity,
                "policy_error": policy_outcome.error,
            },
            metadata={"module_name": context.get("module_name", "")},
        )

    def _configured_mode(self) -> str:
        return (self.config.strategy.mode or "shadow").strip().lower()

    def _effective_mode(self, configured_mode: str) -> str:
        forced = (self.config.strategy.force_mode or "").strip().lower()
        if forced in {"shadow", "advisory"}:
            return forced
        return configured_mode
