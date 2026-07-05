"""Optional Telegram alerts for fills, stops, and API errors."""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request

from intraday_agent.config import Config

logger = logging.getLogger(__name__)


def _telegram_configured() -> bool:
    return bool(
        Config.ALERTS_ENABLED
        and Config.TELEGRAM_BOT_TOKEN
        and Config.TELEGRAM_CHAT_ID
    )


def send_alert(message: str) -> None:
    """Send a Telegram message when alerts are enabled."""
    if not _telegram_configured():
        return
    text = message.strip()
    if not text:
        return
    token = Config.TELEGRAM_BOT_TOKEN
    chat_id = Config.TELEGRAM_CHAT_ID
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage?"
        + urllib.parse.urlencode({"chat_id": chat_id, "text": text})
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status >= 400:
                logger.warning("Telegram alert failed: HTTP %s", resp.status)
    except Exception as exc:
        logger.warning("Telegram alert error: %s", exc)


def alert_trade(action: str, symbol: str, side: str, qty: int, price: float, note: str = "") -> None:
    msg = f"{action} {side} {symbol} x{qty} @ {price:.2f}"
    if note:
        msg = f"{msg} — {note}"
    send_alert(msg)
