"""NFT Mint activity module."""

import time
from typing import Dict, Any

from loguru import logger

from .activity_base import ActivityModule
from .config import Config


class NFTMintModule(ActivityModule):
    """Mint NFTs on testnet marketplaces."""

    def __init__(self, config: Config, wallet: "WalletManager", db: "MetricsDB"):
        """Initialize NFT mint module."""
        super().__init__(config, wallet, db)
        self.module_name = "nft_mint"

        # Placeholder NFT collection address
        self.collection_address = "0x..."  # TODO: Find active testnet collections

    def can_run(self) -> tuple[bool, str]:
        """Check if NFT mint is available."""
        if not self.config.activity.allow_stubs:
            return False, "NFT mint module is not implemented (set ACTIVITY_ALLOW_STUBS=true to enable simulation)"
        return True, "OK (stub simulation)"

    async def run(self) -> Dict[str, Any]:
        """Execute NFT mint (placeholder)."""
        start_time = time.time()
        actions = 0

        try:
            logger.warning("NFT mint module is a stub simulation (no on-chain activity)")
            actions = 0

            # Placeholder: simulate minting
            await self._simulate_mint()

            duration = time.time() - start_time
            self.log_run(duration, actions, True)
            return {
                "module": self.module_name,
                "success": True,
                "skipped": True,
                "reason": "stub_simulation",
                "actions": actions,
                "duration": duration
            }

        except Exception as e:
            logger.error(f"NFT mint failed: {e}")
            duration = time.time() - start_time
            self.log_run(duration, actions, False, str(e))
            return {
                "module": self.module_name,
                "success": False,
                "error": str(e),
                "actions": actions,
                "duration": duration
            }

    async def _simulate_mint(self):
        """Simulate NFT minting."""
        await self._simulate_delay(2)
        logger.info("Simulated: minted NFT from test collection")

    async def _simulate_delay(self, seconds: float):
        """Simulate network delay."""
        import asyncio
        await asyncio.sleep(seconds)
