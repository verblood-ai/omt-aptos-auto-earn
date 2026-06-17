"""Telegram notification sender."""

from typing import Optional

import httpx
from loguru import logger


class TelegramNotifier:
    """Sends notifications via Telegram bot."""

    def __init__(self, bot_token: str, chat_id: str):
        """Initialize Telegram notifier."""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True
                    }
                )
                if response.status_code == 200:
                    logger.info(f"Telegram message sent: {text[:50]}...")
                    return True
                else:
                    logger.error(f"Telegram send failed: {response.status_code} {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def send_notification(self, title: str, message: str, success: bool = True):
        """Send a formatted notification."""
        emoji = "✅" if success else "❌"
        text = f"{emoji} <b>{title}</b>\n\n{message}"
        await self.send_message(text)
