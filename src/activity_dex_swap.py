"""DEX Swap activity module using Liquidswap V2."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from aptos_sdk.transactions import EntryFunction, TransactionArgument, Serializer
from aptos_sdk.type_tag import TypeTag, StructTag

from .activity_base import ActivityModule
from .config import Config


def classify_swap_error(message: str) -> str:
    """
    Map VM / client text to a small set of categories for logs and metadata.

    Categories: linker, slippage, liquidity, insufficient_balance, rpc, unknown
    """
    if not message:
        return "unknown"
    m = message.lower()
    if "linker" in m or ("module " in m and "doesn't exist" in m):
        return "linker"
    if "not published" in m or ("could not find" in m and "module" in m):
        return "linker"
    if "insufficient" in m and "balance" in m:
        return "insufficient_balance"
    if "account" in m and "not registered" in m and "coin" in m:
        return "insufficient_balance"
    if "slippage" in m or "below minimum" in m or "min_out" in m or "minimum amount" in m:
        return "slippage"
    if "e_div" in m or "liquidity" in m or "reserve" in m or ("pool" in m and "empty" in m):
        return "liquidity"
    if "timeout" in m or "timed out" in m:
        return "rpc"
    if "connection" in m or "502" in m or "503" in m or "504" in m:
        return "rpc"
    return "unknown"


def is_network_exception(exc: BaseException) -> bool:
    """True for transport-layer failures where a short retry may help."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return True
    text = str(exc).lower()
    if any(x in text for x in ("timeout", "connection reset", "connection refused", "temporarily unavailable")):
        return True
    mod = getattr(exc, "__module__", "") or ""
    if mod.startswith("httpx"):
        return True
    return False


def parse_deposit_amount_for_coin(events: Any, coin_type: str) -> Optional[int]:
    """Read amount from 0x1::coin::DepositEvent<coin_type> in user transaction or simulation events."""
    if not isinstance(events, list):
        return None
    marker = f"::DepositEvent<{coin_type}>"
    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = ev.get("type", "")
        if not isinstance(et, str) or "DepositEvent<" not in et:
            continue
        if coin_type not in et:
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        raw = data.get("amount")
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


class DexSwapModule(ActivityModule):
    """Perform token swaps on Liquidswap DEX using V2 scripts."""

    TOKEN_APT = "0x1::aptos_coin::AptosCoin"

    def __init__(self, config: Config, wallet: "WalletManager", db: "MetricsDB"):
        """Initialize DEX module."""
        super().__init__(config, wallet, db)
        self.module_name = "dex_swap"

        self.router_address = (config.contracts.liquidswap_router or "").strip()
        self.test_coins_address = (getattr(config.contracts, "liquidswap_test_coins", "") or "").strip()
        if not self.test_coins_address:
            self.test_coins_address = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9"

        self.swap_from_token = self.TOKEN_APT
        self.swap_to_token = f"{self.test_coins_address}::coins::USDT"

        logger.info(f"Liquidswap router: {self.router_address}")
        logger.info(f"DEX pair: {self.swap_from_token} -> {self.swap_to_token}")

        self.slippage = float(getattr(config.activity, "dex_slippage", 0.01))
        self.slippage = min(max(self.slippage, 0.0), 0.5)
        self.min_amount_factor = 1.0 - self.slippage

        self.swap_amount = int(getattr(config.activity, "dex_swap_amount", 1_000_000))
        self.curve_type = f"{self.router_address}::curves::Uncorrelated"

        self._network_retries = 2
        self._retry_base_delay_s = 1.0

    def _build_entry_function(self, from_token: str, to_token: str, amount: int, min_out: int) -> EntryFunction:
        """Build EntryFunction for Liquidswap V2 ``scripts_v2::swap``."""
        token_x = StructTag.from_str(from_token)
        token_y = StructTag.from_str(to_token)
        curve_tag = StructTag.from_str(self.curve_type)
        type_args = [TypeTag(token_x), TypeTag(token_y), TypeTag(curve_tag)]
        module = f"{self.router_address}::scripts_v2"
        return EntryFunction.natural(
            module,
            "swap",
            type_args,
            [
                TransactionArgument(amount, Serializer.u64),
                TransactionArgument(min_out, Serializer.u64),
            ],
        )

    def can_run(self) -> tuple[bool, str]:
        """Check static prerequisites before the async run starts."""
        if not self.router_address.startswith("0x"):
            return False, "Liquidswap router is not configured"
        if not self.test_coins_address.startswith("0x"):
            return False, "Liquidswap test coins address is not configured"
        if self.swap_amount <= 0:
            return False, "Swap amount must be positive"
        if self.swap_from_token == self.swap_to_token:
            return False, "Swap tokens must differ"
        return True, "OK"

    async def _simulate_network_safe(
        self, entry_func: EntryFunction
    ) -> Tuple[bool, List[Any], str]:
        """Simulate with retries only for transport-level failures."""
        delay = self._retry_base_delay_s
        last_err = ""
        for attempt in range(self._network_retries + 1):
            try:
                return await self.wallet.simulate_transaction(entry_func)
            except Exception as exc:
                last_err = str(exc)
                if is_network_exception(exc) and attempt < self._network_retries:
                    logger.warning(f"Simulate network error (retry {attempt + 1}): {exc}")
                    await asyncio.sleep(delay)
                    delay *= 2.0
                    continue
                return False, [], last_err or repr(exc)
        return False, [], last_err

    async def _submit_network_safe(self, entry_func: EntryFunction) -> str:
        delay = self._retry_base_delay_s
        last: Optional[Exception] = None
        for attempt in range(self._network_retries + 1):
            try:
                return await self.wallet.submit_transaction(entry_func)
            except Exception as exc:
                last = exc
                if is_network_exception(exc) and attempt < self._network_retries:
                    logger.warning(f"Submit network error (retry {attempt + 1}): {exc}")
                    await asyncio.sleep(delay)
                    delay *= 2.0
                    continue
                raise
        raise last if last else RuntimeError("submit_transaction failed")

    @staticmethod
    def _token_symbol(token_type: str) -> str:
        return token_type.split("::")[-1].replace("Coin", "").upper()

    def _failure_result(
        self,
        *,
        start_time: float,
        actions: int,
        error: str,
        error_class: str,
        skipped: bool = False,
        reason: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        duration = time.time() - start_time
        self.log_run(duration, actions, False, error)
        out: Dict[str, Any] = {
            "module": self.module_name,
            "success": False,
            "skipped": skipped,
            "reason": reason or error_class,
            "error": error,
            "error_class": error_class,
            "actions": actions,
            "duration": duration,
        }
        if extra:
            out.update(extra)
        return out

    async def run(self) -> Dict[str, Any]:
        """Execute a swap on Liquidswap V2 (simulate → submit only if simulation succeeds)."""
        start_time = time.time()
        actions = 0
        tx_hash: Optional[str] = None

        try:
            balance = await self.wallet.get_balance()
            balance_octas = int(balance * 100_000_000)

            if balance_octas < self.swap_amount:
                logger.info(f"Insufficient balance: {balance_octas} < {self.swap_amount}")
                duration = time.time() - start_time
                self.log_run(duration, actions, True)
                return {
                    "module": self.module_name,
                    "success": True,
                    "skipped": True,
                    "reason": "insufficient_balance",
                    "error_class": "insufficient_balance",
                    "balance": balance_octas,
                    "required": self.swap_amount,
                    "actions": actions,
                    "duration": duration,
                }

            # Probe simulation with minimal min_out to read expected output from events.
            probe_entry = self._build_entry_function(
                self.swap_from_token,
                self.swap_to_token,
                self.swap_amount,
                1,
            )
            logger.info("Simulating swap (probe, min_out=1)…")
            ok_probe, probe_results, probe_err = await self._simulate_network_safe(probe_entry)
            if not ok_probe:
                err_text = probe_err or ""
                if probe_results:
                    for tx in probe_results:
                        if isinstance(tx, dict) and tx.get("vm_status"):
                            err_text = str(tx.get("vm_status"))
                            break
                ec = classify_swap_error(err_text)
                logger.error(f"Simulation (probe) failed [{ec}]: {err_text}")
                return self._failure_result(
                    start_time=start_time,
                    actions=0,
                    error=err_text or "simulation_failed",
                    error_class=ec,
                    skipped=True,
                    reason="simulation_failed",
                    extra={"simulation_phase": "probe"},
                )

            probe_tx0: Dict[str, Any] = probe_results[0] if probe_results and isinstance(probe_results[0], dict) else {}
            events_probe = probe_tx0.get("events") or []
            quoted_out = parse_deposit_amount_for_coin(events_probe, self.swap_to_token)
            if quoted_out is None or quoted_out <= 0:
                logger.warning("Could not parse expected output from probe simulation; using conservative min_out=1")
                quoted_out = 1

            min_amount_out = max(1, int(quoted_out * self.min_amount_factor))
            logger.info(
                f"Swap: {self.swap_amount} octas in, probe expected ~{quoted_out} octas {self._token_symbol(self.swap_to_token)}, min_out {min_amount_out} (slippage {self.slippage})"
            )

            entry_func = self._build_entry_function(
                self.swap_from_token,
                self.swap_to_token,
                self.swap_amount,
                min_amount_out,
            )

            logger.info("Simulating swap (final min_out)…")
            ok_final, final_results, final_err = await self._simulate_network_safe(entry_func)
            if not ok_final:
                err_text = final_err or ""
                if final_results:
                    for tx in final_results:
                        if isinstance(tx, dict) and tx.get("vm_status"):
                            err_text = str(tx.get("vm_status"))
                            break
                ec = classify_swap_error(err_text)
                logger.error(f"Simulation (final) failed [{ec}]: {err_text}")
                return self._failure_result(
                    start_time=start_time,
                    actions=0,
                    error=err_text or "simulation_failed",
                    error_class=ec,
                    skipped=True,
                    reason="simulation_failed",
                    extra={
                        "simulation_phase": "final",
                        "quoted_amount_out": quoted_out,
                        "min_amount_out": min_amount_out,
                    },
                )

            final_tx0: Dict[str, Any] = final_results[0] if final_results and isinstance(final_results[0], dict) else {}
            sim_amount_out = parse_deposit_amount_for_coin(final_tx0.get("events") or [], self.swap_to_token)
            if sim_amount_out is None:
                sim_amount_out = quoted_out

            logger.info("Submitting swap transaction…")
            tx_hash = await self._submit_network_safe(entry_func)
            logger.info(f"Swap transaction submitted: {tx_hash}")

            confirmed = await self.wallet.wait_for_transaction(tx_hash, timeout_seconds=60)
            committed_out: Optional[int] = None
            if confirmed:
                details = await self.wallet.get_transaction_details(tx_hash)
                if isinstance(details, dict):
                    committed_out = parse_deposit_amount_for_coin(details.get("events") or [], self.swap_to_token)
            else:
                logger.warning(f"Swap tx submitted but confirmation timed out: {tx_hash}")
                duration = time.time() - start_time
                self.log_run(duration, 0, False, "confirmation_timeout")
                self.db.insert_transaction(
                    tx_hash=tx_hash,
                    network=self.config.network,
                    tx_type=self.module_name,
                    amount=self.swap_amount / 10**8,
                    token_symbol=self._token_symbol(self.swap_from_token),
                    status="timeout",
                    metadata={
                        "from_token": self.swap_from_token,
                        "to_token": self.swap_to_token,
                        "error_class": "rpc",
                        "note": "Submitted; confirmation wait timed out",
                    },
                )
                return {
                    "module": self.module_name,
                    "success": False,
                    "skipped": True,
                    "reason": "confirmation_timeout",
                    "error": "Swap transaction was submitted but not confirmed in time",
                    "error_class": "rpc",
                    "actions": 0,
                    "tx_hash": tx_hash,
                    "duration": duration,
                }

            amount_out_for_metrics = float(committed_out if committed_out is not None else sim_amount_out)

            actions = 1
            duration = time.time() - start_time
            self.log_run(duration, actions, True)

            self.db.insert_transaction(
                tx_hash=tx_hash,
                network=self.config.network,
                tx_type=self.module_name,
                amount=self.swap_amount / 10**8,
                token_symbol=self._token_symbol(self.swap_from_token),
                status="success",
                metadata={
                    "from_token": self.swap_from_token,
                    "to_token": self.swap_to_token,
                    "amount_in_octas": self.swap_amount,
                    "quoted_amount_out": quoted_out,
                    "simulated_amount_out": sim_amount_out,
                    "committed_amount_out": committed_out,
                    "min_amount_out": min_amount_out,
                },
            )

            self.db.record_swap(
                from_token=self._token_symbol(self.swap_from_token),
                to_token=self._token_symbol(self.swap_to_token),
                amount_in=float(self.swap_amount),
                amount_out=amount_out_for_metrics,
                tx_hash=tx_hash,
                success=True,
            )

            return {
                "module": self.module_name,
                "success": True,
                "actions": actions,
                "tx_hash": tx_hash,
                "from_token": self.swap_from_token,
                "to_token": self.swap_to_token,
                "amount_in": self.swap_amount,
                "quoted_amount_out": quoted_out,
                "amount_out_actual": committed_out if committed_out is not None else sim_amount_out,
                "duration": duration,
            }

        except Exception as e:
            err_text = str(e)
            ec = classify_swap_error(err_text)
            if is_network_exception(e):
                ec = "rpc"
            logger.error(f"DEX swap failed [{ec}]: {e}")
            if tx_hash:
                self.db.insert_transaction(
                    tx_hash=tx_hash,
                    network=self.config.network,
                    tx_type=self.module_name,
                    amount=self.swap_amount / 10**8,
                    token_symbol=self._token_symbol(self.swap_from_token),
                    status="failed",
                    metadata={
                        "from_token": self.swap_from_token,
                        "to_token": self.swap_to_token,
                        "error": err_text,
                        "error_class": ec,
                    },
                )
            return self._failure_result(
                start_time=start_time,
                actions=actions,
                error=err_text,
                error_class=ec,
                extra={"tx_hash": tx_hash} if tx_hash else {},
            )
