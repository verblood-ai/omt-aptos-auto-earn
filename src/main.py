#!/usr/bin/env python3
"""
Aptos Auto Earn - Main Orchestrator

Automated earnings on Aptos testnet:
- Faucet claims (1 APT per day)
- Activity (DEX swaps, lending, NFT mint)
- Airdrop monitoring
"""

import asyncio
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import schedule
from loguru import logger

from .config import Config, PROJECT_ROOT
from .database import MetricsDB
from .wallet import WalletManager
from .faucet import FaucetManager
from .airdrop_monitor import AirdropMonitor
from .telegram_notifier import TelegramNotifier
from .dex_diagnostics import check_liquidswap_modules
from .kpi_alerts import KPIAlertState, KPIEvaluator
from .policy_engine import PolicyEngine
from .readiness_gate import ReadinessGate
from .strategy_engine import StrategyDecision, StrategyEngine

# Import activity modules
from .activity_dex_swap import DexSwapModule
from .activity_lending import LendingModule
from .activity_nft_mint import NFTMintModule


class AptosAutoEarn:
    """Main orchestrator class."""

    def __init__(self):
        """Initialize all components."""
        # Load configuration
        self.config = Config.load()
        self._setup_logging()

        logger.info("=" * 60)
        logger.info("APTOS AUTO EARN - Starting")
        logger.info(f"Network: {self.config.network}")
        logger.info(f"Wallet: Will be loaded/created")
        logger.info("=" * 60)

        # Initialize database
        self.db = MetricsDB(self.config.metrics.db_path)

        # Initialize wallet
        self.wallet = WalletManager(self.config)
        logger.info(f"Wallet address: {self.wallet.address}")

        # Initialize components
        self.faucet = FaucetManager(self.config, self.db, self.wallet)
        self.airdrop_monitor = AirdropMonitor(self.config, self.db)

        # Initialize activity modules
        self.activity_modules = []
        if self.config.activity.enabled:
            self.activity_modules = self._build_activity_modules()
            logger.info(f"Activity modules enabled: {[m.module_name for m in self.activity_modules]}")

        # Initialize Telegram notifier if configured
        self.telegram = None
        if self.config.telegram.enabled and self.config.telegram.bot_token and self.config.telegram.chat_id:
            self.telegram = TelegramNotifier(
                self.config.telegram.bot_token,
                self.config.telegram.chat_id
            )
            logger.info("Telegram notifications enabled")

        # Runtime safety / strategy / KPI evaluators
        self.readiness_gate = ReadinessGate(self.config)
        self.policy_engine = PolicyEngine(self.config, self.db)
        self.strategy_engine = StrategyEngine(self.config, self.policy_engine)
        self.kpi_evaluator = KPIEvaluator(self.config, self.db)
        self.kpi_alert_state = KPIAlertState(
            PROJECT_ROOT / "data" / "kpi_alert_state.json",
            cooldown_minutes=self.config.kpi_alerts.cooldown_minutes,
        )

        # Schedule state
        self.running = True
        self._scheduled_job_queue: asyncio.Queue[str] = asyncio.Queue()
        self._scheduled_jobs_enqueued: set[str] = set()
        self._activity_last_run_at: datetime | None = None
        self._activity_min_interval_minutes = max(0, int(self.config.activity.min_interval_minutes))
        self._dex_preflight_checked = False
        self._dex_preflight_ok = True
        self._dex_preflight_error = ""
        self._last_readiness_state: dict[str, tuple[bool, str]] = {}
        self._last_gate_log_at: dict[str, datetime] = {}
        self._last_gate_reason: dict[str, str] = {}
        self._last_advisory_sent_at: dict[str, datetime] = {}
        self._last_advisory_reason: dict[str, str] = {}
        self._last_kpi_eval_at: datetime | None = None
        self._setup_signal_handlers()

    def _setup_logging(self):
        """Configure loguru logging."""
        log_level = self.config.logging.level
        log_file = self.config.logging.file

        # Ensure log directory exists
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        # Remove default handler
        logger.remove()

        # Add console handler
        logger.add(
            sys.stdout,
            level=log_level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )

        # Add file handler
        logger.add(
            log_file,
            level=log_level,
            rotation=self.config.logging.rotation,
            retention=self.config.logging.retention,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals (SIGINT / SIGTERM for Ctrl+C and systemd stop)."""
        logger.warning(f"Received signal {signum}, stopping scheduler loop...")
        self.running = False

    async def run_faucet_cycle(self):
        """Execute one faucet claim cycle."""
        logger.info("Starting faucet cycle...")

        can_claim, reason = self.faucet.can_claim()
        if can_claim:
            success = await self.faucet.claim()
            if success and self.telegram:
                await self.telegram.send_notification(
                    "Faucet Claimed",
                    f"✅ Successfully claimed {self.faucet.format_amount()}\nWallet: {self.wallet.address}",
                    success=True
                )
        else:
            logger.info(f"Faucet skip: {reason}")

    async def _ensure_dex_preflight(self) -> bool:
        """Run Liquidswap module check once before first dex_swap execution."""
        if self._dex_preflight_checked:
            return self._dex_preflight_ok

        self._dex_preflight_checked = True
        logger.info("Running Liquidswap pre-flight check (scripts_v2/router_v2)...")
        report = await check_liquidswap_modules(self.config, required=("scripts_v2", "router_v2"))
        self._dex_preflight_ok = bool(report.get("ok"))

        if self._dex_preflight_ok:
            logger.info(
                "Liquidswap pre-flight passed: router={} modules_found={}",
                report.get("liquidswap_router"),
                report.get("modules_found"),
            )
            return True

        status = report.get("status") or {}
        missing = [name for name, present in status.items() if not present]
        error = report.get("error") or ""
        parts = []
        if missing:
            parts.append(f"missing modules: {', '.join(missing)}")
        if error:
            parts.append(f"error: {error}")
        self._dex_preflight_error = "; ".join(parts) if parts else "Liquidswap modules check failed"
        logger.error(
            "Liquidswap pre-flight failed; dex_swap will be skipped until restart: {}",
            self._dex_preflight_error,
        )
        return False

    def _log_gate_reason_once(self, module_name: str, reason: str) -> None:
        dedup_window = max(0, int(self.config.readiness.dedup_log_window_seconds))
        now = datetime.now(timezone.utc)
        last_reason = self._last_gate_reason.get(module_name)
        last_at = self._last_gate_log_at.get(module_name)
        if last_reason == reason and last_at is not None and dedup_window > 0:
            if (now - last_at).total_seconds() < dedup_window:
                return
        logger.warning("Module {} blocked by readiness gate: {}", module_name, reason)
        self._last_gate_reason[module_name] = reason
        self._last_gate_log_at[module_name] = now

    def _record_readiness_transition(self, module_name: str, ready: bool, reason: str, signals: dict) -> None:
        prev = self._last_readiness_state.get(module_name)
        if prev == (ready, reason):
            return
        self._last_readiness_state[module_name] = (ready, reason)
        self.db.insert_readiness_event(
            module_name=module_name,
            status="ready" if ready else "blocked",
            reason=reason,
            source="orchestrator_gate",
            metadata={"signals": signals},
        )

    def _record_activity_skip(
        self,
        *,
        module_name: str,
        reason: str,
        gate_reason: str = "",
        error_class: str = "skip",
        metadata: dict | None = None,
    ) -> None:
        self.db.insert_activity_run(
            module_name=module_name,
            duration_seconds=0.0,
            actions_performed=0,
            success=True,
            error_message=None,
            skipped=True,
            skip_reason=reason,
            error_class=error_class,
            gate_reason=gate_reason or reason,
            retry_count=0,
            metadata=metadata or {},
        )

    async def _maybe_send_advisory_notice(
        self,
        *,
        module_name: str,
        decision: StrategyDecision,
        correlation_id: str,
    ) -> None:
        if not decision.advisory_notice:
            return
        if not self.telegram:
            return

        key = f"{module_name}:{decision.severity}"
        now = datetime.now(timezone.utc)
        cooldown_minutes = max(1, int(self.config.strategy.advisory_cooldown_minutes))
        last_at = self._last_advisory_sent_at.get(key)
        last_reason = self._last_advisory_reason.get(key)
        if last_reason == decision.reason and last_at is not None:
            if (now - last_at).total_seconds() < cooldown_minutes * 60:
                return

        self._last_advisory_sent_at[key] = now
        self._last_advisory_reason[key] = decision.reason
        await self.telegram.send_notification(
            "Strategy Advisory",
            (
                f"module={module_name}\n"
                f"mode={decision.effective_mode}\n"
                f"action={decision.action}\n"
                f"reason={decision.reason}\n"
                f"correlation_id={correlation_id}"
            ),
            success=False,
        )

    async def _evaluate_and_alert_kpis(self, trigger: str) -> None:
        if not self.config.kpi_alerts.enabled:
            return
        interval = max(1, int(self.config.kpi_alerts.evaluation_interval_minutes))
        now = datetime.now(timezone.utc)
        if self._last_kpi_eval_at is not None:
            elapsed = (now - self._last_kpi_eval_at).total_seconds()
            if elapsed < interval * 60:
                return
        self._last_kpi_eval_at = now

        runtime_signals = {
            "last_faucet_success_ts": self.db.get_last_faucet_success_ts(),
            "last_airdrop_check_ts": self.airdrop_monitor.state.get("last_check"),
        }
        snapshot = self.kpi_evaluator.evaluate(runtime_signals=runtime_signals)
        logger.info("KPI snapshot trigger={} severity={} metrics={}", trigger, snapshot.get("severity"), snapshot.get("metrics"))
        events = self.kpi_alert_state.build_events(snapshot)
        for event in events:
            metric = event["metric"]
            if event["type"] == "alert":
                text = (
                    f"KPI={metric['key']} severity={metric['severity']} value={metric['value']:.4f} "
                    f"warn={metric['warn_threshold']:.4f} critical={metric['critical_threshold']:.4f}"
                )
                logger.warning("KPI alert: {}", text)
                if self.telegram:
                    await self.telegram.send_notification("KPI Alert", text, success=False)
            elif event["type"] == "recovery":
                text = f"KPI={metric['key']} recovered to OK (value={metric['value']:.4f})"
                logger.info("KPI recovery: {}", text)
                if self.telegram:
                    await self.telegram.send_notification("KPI Recovery", text, success=True)

    async def run_activity_cycle(self):
        """Execute one activity cycle."""
        now = datetime.now(timezone.utc)
        if self._activity_min_interval_minutes > 0 and self._activity_last_run_at is not None:
            min_interval_seconds = self._activity_min_interval_minutes * 60
            elapsed_seconds = (now - self._activity_last_run_at).total_seconds()
            if elapsed_seconds < min_interval_seconds:
                wait_seconds = int(min_interval_seconds - elapsed_seconds)
                logger.info(
                    "Activity cycle throttled by min_interval_minutes={} (wait ~{}s)",
                    self._activity_min_interval_minutes,
                    wait_seconds,
                )
                return
        self._activity_last_run_at = now

        logger.info("Starting activity cycle...")

        # Check balance first
        rpc_ok = True
        rpc_error = ""
        try:
            balance = await self.wallet.get_balance()
        except Exception as exc:  # noqa: BLE001
            balance = 0.0
            rpc_ok = False
            rpc_error = str(exc)
        logger.info(f"Current APT balance: {balance}")

        has_dex_module = any(module.module_name == "dex_swap" for module in self.activity_modules)
        dex_preflight_ok = True
        if has_dex_module:
            dex_preflight_ok = await self._ensure_dex_preflight()

        for module in self.activity_modules:
            can_run, reason = module.can_run()
            if not can_run:
                self._record_activity_skip(
                    module_name=module.module_name,
                    reason="module_can_run_false",
                    gate_reason=reason,
                    error_class="module_precheck_failed",
                    metadata={"source": "module.can_run"},
                )
                logger.debug(f"Module {module.module_name} skipped: {reason}")
                continue

            faucet_can_claim, faucet_reason = self.faucet.can_claim()
            readiness = self.readiness_gate.evaluate(
                module_name=module.module_name,
                balance_apt=balance,
                rpc_ok=rpc_ok,
                rpc_error=rpc_error,
                dex_preflight_ok=dex_preflight_ok,
                dex_preflight_error=self._dex_preflight_error,
                faucet_can_claim=faucet_can_claim,
                faucet_reason=faucet_reason,
            )
            self._record_readiness_transition(
                module_name=module.module_name,
                ready=readiness.ready,
                reason=readiness.reason,
                signals=readiness.signal_snapshot,
            )
            if not readiness.ready:
                self._log_gate_reason_once(module.module_name, readiness.reason)
                self._record_activity_skip(
                    module_name=module.module_name,
                    reason="readiness_blocked",
                    gate_reason=readiness.reason,
                    error_class="readiness_blocked",
                    metadata={"signals": readiness.signal_snapshot},
                )
                continue

            correlation_id = uuid.uuid4().hex
            decision = self.strategy_engine.evaluate(
                {
                    "module_name": module.module_name,
                    "balance_apt": balance,
                    "readiness_reason": readiness.reason,
                }
            )
            if self.config.strategy.enabled:
                self.db.insert_strategy_decision(
                    correlation_id=correlation_id,
                    module_name=module.module_name,
                    mode=decision.mode,
                    effective_mode=decision.effective_mode,
                    action=decision.action,
                    severity=decision.severity,
                    reason=decision.reason,
                    stage="pre",
                    outcome="pending",
                    rule_hits=decision.rule_hits,
                    inputs={
                        "balance_apt": balance,
                        "readiness_reason": readiness.reason,
                    },
                    metadata=decision.policy_snapshot,
                )

            await self._maybe_send_advisory_notice(
                module_name=module.module_name,
                decision=decision,
                correlation_id=correlation_id,
            )
            if decision.action in {"block", "defer"}:
                self._record_activity_skip(
                    module_name=module.module_name,
                    reason="policy_denied",
                    gate_reason=decision.reason,
                    error_class="policy_denied",
                    metadata={
                        "mode": decision.mode,
                        "effective_mode": decision.effective_mode,
                        "rule_hits": decision.rule_hits,
                        "correlation_id": correlation_id,
                    },
                )
                if self.config.strategy.enabled:
                    self.db.insert_strategy_decision(
                        correlation_id=correlation_id,
                        module_name=module.module_name,
                        mode=decision.mode,
                        effective_mode=decision.effective_mode,
                        action=decision.action,
                        severity=decision.severity,
                        reason=decision.reason,
                        stage="post",
                        outcome="blocked",
                        rule_hits=decision.rule_hits,
                        inputs={"balance_apt": balance},
                        metadata={
                            "remediation_hint": decision.remediation_hint,
                            "policy_snapshot": decision.policy_snapshot,
                        },
                    )
                continue

            logger.info(f"Running module: {module.module_name}")
            result = await module.run()
            if decision.action == "warn" and not result.get("skipped"):
                result["executed_despite_advisory"] = True
            if result["success"]:
                if result.get("skipped"):
                    logger.info(
                        f"Module {module.module_name} skipped: {result.get('reason')} "
                        f"({result.get('duration', 0):.2f}s)"
                    )
                else:
                    actions = result.get("actions", 0)
                    duration = result.get("duration", 0.0)
                    logger.info(
                        f"Module {module.module_name} completed: {actions} actions in {duration:.2f}s"
                    )
            elif result.get("skipped"):
                logger.info(
                    f"Module {module.module_name} skipped (no on-chain action): "
                    f"{result.get('reason')} class={result.get('error_class')} "
                    f"— {result.get('error', '')} ({result.get('duration', 0):.2f}s)"
                )
            else:
                logger.warning(f"Module {module.module_name} failed: {result.get('error')}")

            if self.config.strategy.enabled:
                if result.get("skipped"):
                    outcome = "skipped"
                elif result.get("success"):
                    outcome = "executed"
                else:
                    outcome = "failed"
                self.db.insert_strategy_decision(
                    correlation_id=correlation_id,
                    module_name=module.module_name,
                    mode=decision.mode,
                    effective_mode=decision.effective_mode,
                    action=decision.action,
                    severity=decision.severity,
                    reason=decision.reason,
                    stage="post",
                    outcome=outcome,
                    rule_hits=decision.rule_hits,
                    inputs={
                        "balance_apt": balance,
                        "readiness_reason": readiness.reason,
                    },
                    metadata={
                        "result": {
                            "success": bool(result.get("success")),
                            "skipped": bool(result.get("skipped")),
                            "reason": result.get("reason", ""),
                            "error": result.get("error", ""),
                            "executed_despite_advisory": bool(result.get("executed_despite_advisory", False)),
                        },
                        "correlation_id": correlation_id,
                    },
                )

        await self._evaluate_and_alert_kpis(trigger="activity_cycle")

    async def run_airdrop_cycle(self):
        """Execute airdrop monitoring cycle."""
        logger.info("Starting airdrop monitoring...")

        if not self.config.airdrop.enabled:
            logger.debug("Airdrop monitoring disabled in config")
            return

        can_check, reason = self.airdrop_monitor.should_check()
        if not can_check:
            logger.debug(f"Airdrop check skipped: {reason}")
            return

        new_airdrops = await self.airdrop_monitor.check_all_sources()

        if new_airdrops:
            logger.info(f"Found {len(new_airdrops)} new airdrop(s)!")

            for airdrop in new_airdrops:
                self.db.insert_airdrop(
                    name=airdrop["name"],
                    network=airdrop["network"],
                    value_estimate=airdrop.get("value_estimate", 0.0),
                    url=airdrop["url"]
                )
                logger.info(f"Airdrop: {airdrop['name']} - {airdrop.get('value_estimate', 'N/A')} USD")

            if self.telegram:
                message = "🛬 New airdrops found:\n\n"
                for airdrop in new_airdrops:
                    message += f"• {airdrop['name']}\n  {airdrop.get('value_estimate', 'N/A')} USD\n  {airdrop['url']}\n\n"
                await self.telegram.send_message(message)
        else:
            logger.info("No new airdrops found")

    async def run_balance_check(self):
        """Record current balance to database."""
        balance = await self.wallet.get_balance()
        self.db.insert_balance(
            network=self.config.network,
            token_symbol="APT",
            balance=balance,
            usd_value=None  # TODO: Fetch APT price from API
        )
        logger.debug(f"Balance recorded: {balance} APT")

    def _enqueue_scheduled_job(self, job_name: str):
        """Queue periodic jobs and avoid duplicate backlog entries."""
        if job_name in self._scheduled_jobs_enqueued:
            logger.debug(f"Scheduled job already queued: {job_name}")
            return
        self._scheduled_jobs_enqueued.add(job_name)
        self._scheduled_job_queue.put_nowait(job_name)

    async def _run_queued_jobs(self):
        """Run scheduled jobs sequentially inside the main asyncio loop."""
        while not self._scheduled_job_queue.empty() and self.running:
            job_name = await self._scheduled_job_queue.get()
            self._scheduled_jobs_enqueued.discard(job_name)
            try:
                if job_name == "faucet":
                    await self.run_faucet_cycle()
                elif job_name == "activity":
                    await self.run_activity_cycle()
                elif job_name == "airdrop":
                    await self.run_airdrop_cycle()
                elif job_name == "balance":
                    await self.run_balance_check()
                else:
                    logger.warning(f"Unknown scheduled job: {job_name}")
            except Exception as exc:
                logger.exception(f"Scheduled job '{job_name}' failed: {exc}")

    def schedule_jobs(self):
        """Schedule all periodic jobs (intervals from `config.scheduler`)."""
        sch = self.config.scheduler
        airdrop_interval_hours = int(self.config.airdrop.check_interval_hours)
        if int(sch.airdrop_interval_hours) != airdrop_interval_hours:
            logger.warning(
                "scheduler.airdrop_interval_hours={} differs from airdrop.check_interval_hours={}; using airdrop value as source of truth",
                sch.airdrop_interval_hours,
                airdrop_interval_hours,
            )

        schedule.every().day.at(sch.faucet_daily_at).do(self._enqueue_scheduled_job, "faucet")

        schedule.every(sch.activity_interval_hours).hours.do(self._enqueue_scheduled_job, "activity")

        schedule.every(airdrop_interval_hours).hours.do(self._enqueue_scheduled_job, "airdrop")

        schedule.every(sch.balance_interval_hours).hours.do(self._enqueue_scheduled_job, "balance")

        logger.info("Jobs scheduled:")
        logger.info(f"  - Faucet: daily at {sch.faucet_daily_at}")
        logger.info(f"  - Activity: every {sch.activity_interval_hours} hours")
        logger.info(f"  - Airdrop check: every {airdrop_interval_hours} hours")
        logger.info(f"  - Balance check: every {sch.balance_interval_hours} hour(s)")

    async def run_once(self):
        """Run all cycles once (for testing)."""
        logger.info("Running single cycle (test mode)...")

        await self.run_balance_check()
        await self.run_faucet_cycle()
        await self.run_activity_cycle()
        await self.run_airdrop_cycle()
        await self._evaluate_and_alert_kpis(trigger="run_once")

        logger.info("Single cycle completed")

    async def run_scheduler(self):
        """Run the scheduler loop."""
        self.schedule_jobs()

        # Run initial balance check immediately
        await self.run_balance_check()

        logger.info("Scheduler started, waiting for jobs...")

        while self.running:
            schedule.run_pending()
            await self._run_queued_jobs()
            await asyncio.sleep(1)

        logger.info("Scheduler loop exited (shutdown)")

    async def run(self):
        """Main entry point."""
        try:
            # Check if we should run once or as daemon
            if len(sys.argv) > 1 and sys.argv[1] == "--once":
                await self.run_once()
            else:
                await self.run_scheduler()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down...")
        schedule.clear()

        # Close database
        self.db.close()

        # Close wallet client
        await self.wallet.close()

        logger.info("Shutdown complete")

    def _build_activity_modules(self):
        """Instantiate activity modules based on config."""
        modules: list = []
        selected = self.config.activity.modules or []

        for name in selected:
            if name == "dex_swap":
                modules.append(DexSwapModule(self.config, self.wallet, self.db))
            elif name == "lending":
                modules.append(LendingModule(self.config, self.wallet, self.db))
            elif name == "nft_mint":
                modules.append(NFTMintModule(self.config, self.wallet, self.db))
            else:
                logger.warning(f"Unknown activity module in config: {name}")

        return modules


def main():
    """CLI entry point."""
    orchestrator = AptosAutoEarn()
    asyncio.run(orchestrator.run())


if __name__ == "__main__":
    main()
