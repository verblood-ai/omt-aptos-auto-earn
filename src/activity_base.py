"""Base class for activity modules."""

import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List

from loguru import logger
from .database import MetricsDB


class ActivityModule(ABC):
    """Base class for all activity modules."""

    def __init__(self, config: "Config", wallet: "WalletManager", db: MetricsDB):
        """Initialize activity module."""
        self.config = config
        self.wallet = wallet
        self.db = db
        self.module_name = self.__class__.__name__

    @abstractmethod
    def can_run(self) -> tuple[bool, str]:
        """Check if module can run (sufficient balance, etc.)."""
        pass

    @abstractmethod
    async def run(self) -> Dict[str, Any]:
        """Execute the activity. Returns result dict."""
        pass

    def log_run(self, duration: float, actions: int, success: bool, error: str = None):
        """Log activity run to database."""
        self.db.insert_activity_run(
            module_name=self.module_name,
            duration_seconds=duration,
            actions_performed=actions,
            success=success,
            error_message=error
        )
