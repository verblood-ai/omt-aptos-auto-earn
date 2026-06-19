"""Lending activity module using Aave or similar."""

import time
from typing import Dict, Any

from loguru import logger

from .activity_base import ActivityModule
from .config import Config


class LendingModule(ActivityModule):
    """Lending/borrowing activity on Aave."""

    def __init__(self, config: Config, wallet: "WalletManager", db: "MetricsDB"):
        """Initialize lending module."""
        super().__init__(config, wallet, db)
        self.module_name = "lending"

        # Aave address on testnet (placeholder)
        self.protocol_address = "0x..."  # TODO: Get actual address

    def can_run(self) -> tuple[bool, str]:
        """Check if lending is possible."""
        if not self.config.activity.allow_stubs:
            return False, "Lending module is not implemented (set ACTIVITY_ALLOW_STUBS=true to enable simulation)"
        return True, "OK (stub simulation)"

    async def run(self) -> Dict[str, Any]:
        """Execute lending activity (placeholder)."""
        start_time = time.time()
        actions = 0

        try:
            logger.warning("Lending module is a stub simulation (no on-chain activity)")
            actions = 0

            # Placeholder: simulate supply/borrow/withdraw
            await self._simulate_lending()

            duration = time.time() - start_time
            self.log_run(
                duration,
                actions,
                True,
                skipped=True,
                skip_reason="stub_simulation",
                error_class="stub",
            )
            return {
                "module": self.module_name,
                "success": True,
                "skipped": True,
                "reason": "stub_simulation",
                "actions": actions,
                "duration": duration
            }

        except Exception as e:
            logger.error(f"Lending failed: {e}")
            duration = time.time() - start_time
            self.log_run(duration, actions, False, str(e))
            return {
                "module": self.module_name,
                "success": False,
                "error": str(e),
                "actions": actions,
                "duration": duration
            }

    async def _simulate_lending(self):
        """Simulate lending operations."""
        await self._simulate_delay(1.5)
        logger.info("Simulated: supplied 0.05 APT to Aave")

    async def _simulate_delay(self, seconds: float):
        """Simulate network delay."""
        import asyncio
        await asyncio.sleep(seconds)
