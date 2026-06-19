"""Readiness gate evaluation for activity execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class ReadinessResult:
    ready: bool
    reason: str
    signal_snapshot: Dict[str, Dict[str, Any]]


class ReadinessGate:
    """Evaluates if a module can execute in current runtime context."""

    def __init__(self, config: "Config"):
        self.config = config

    def evaluate(
        self,
        *,
        module_name: str,
        balance_apt: Optional[float],
        rpc_ok: bool,
        rpc_error: str = "",
        dex_preflight_ok: bool = True,
        dex_preflight_error: str = "",
        faucet_can_claim: Optional[bool] = None,
        faucet_reason: str = "",
    ) -> ReadinessResult:
        checks = set(self.config.readiness.mandatory_checks)
        snapshot: Dict[str, Dict[str, Any]] = {}
        now = datetime.now(timezone.utc).isoformat()

        try:
            rpc_pass = bool(rpc_ok)
            snapshot["rpc_health"] = {
                "ok": rpc_pass,
                "reason": "ok" if rpc_pass else (rpc_error or "rpc_unavailable"),
                "source": "wallet_balance_probe",
                "timestamp": now,
            }

            min_balance = float(self.config.readiness.min_balance_apt)
            balance_value = float(balance_apt if balance_apt is not None else 0.0)
            min_balance_pass = balance_value >= min_balance
            snapshot["min_balance_guard"] = {
                "ok": min_balance_pass,
                "reason": "ok" if min_balance_pass else "insufficient_balance_for_readiness",
                "source": "wallet_balance",
                "balance_apt": balance_value,
                "required_apt": min_balance,
                "timestamp": now,
            }

            dex_required = bool(self.config.readiness.require_dex_preflight) and module_name == "dex_swap"
            dex_pass = True if not dex_required else bool(dex_preflight_ok)
            snapshot["dex_preflight"] = {
                "ok": dex_pass,
                "reason": "ok" if dex_pass else (dex_preflight_error or "dex_preflight_failed"),
                "source": "dex_diagnostics",
                "required": dex_required,
                "timestamp": now,
            }

            faucet_required = bool(self.config.readiness.require_faucet_eligibility)
            if faucet_required:
                faucet_pass = bool(faucet_can_claim)
                faucet_signal_reason = "ok" if faucet_pass else (faucet_reason or "faucet_not_eligible")
            else:
                faucet_pass = True
                faucet_signal_reason = "check_disabled"
            snapshot["faucet_eligibility_freshness"] = {
                "ok": faucet_pass,
                "reason": faucet_signal_reason,
                "source": "faucet_state",
                "required": faucet_required,
                "timestamp": now,
            }

            for check_name in checks:
                if not snapshot.get(check_name, {}).get("ok", True):
                    return ReadinessResult(
                        ready=False,
                        reason=f"readiness_{check_name}:{snapshot[check_name]['reason']}",
                        signal_snapshot=snapshot,
                    )
            return ReadinessResult(ready=True, reason="ready", signal_snapshot=snapshot)
        except Exception as exc:  # noqa: BLE001
            fail_mode = (self.config.readiness.fail_mode or "closed").strip().lower()
            reason = f"readiness_internal_error:{type(exc).__name__}"
            snapshot["readiness_internal"] = {
                "ok": fail_mode == "open",
                "reason": reason,
                "source": "readiness_gate",
                "timestamp": now,
            }
            if fail_mode == "open":
                return ReadinessResult(ready=True, reason=f"{reason}:fail_open", signal_snapshot=snapshot)
            return ReadinessResult(ready=False, reason=reason, signal_snapshot=snapshot)
