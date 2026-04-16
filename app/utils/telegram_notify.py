"""Telegram notification utility via Telegram Bot API (free).

Setup (one-time):
  1. Open Telegram and message @BotFather.
  2. Send /newbot, follow prompts → you receive a BOT_TOKEN.
  3. Start a chat with your new bot (send it any message).
  4. Call https://api.telegram.org/bot<BOT_TOKEN>/getUpdates in a browser
     and find your "id" inside the "chat" object → that is your CHAT_ID.

Configure via environment variables:
  TELEGRAM_BOT_TOKEN  – Token from BotFather  e.g. 123456:ABCdef...
  TELEGRAM_CHAT_ID    – Your personal chat id  e.g. 987654321
"""

import logging
import os
import urllib.request
import json
from html import escape

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _send(message: str) -> bool:
    """Send a Telegram message to the admin chat and report success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set – skipping Telegram notification")
        return False

    url = _BASE_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = json.dumps({
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "PaymentApprovalApp/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            response_body = json.loads(resp.read().decode() or "{}")
        if status != 200 or not response_body.get("ok"):
            logger.warning("Telegram notification failed: HTTP %s | response=%s", status, response_body)
            return False
        logger.info("Telegram notification sent (HTTP %s) to chat %s", status, TELEGRAM_CHAT_ID)
        return True
    except Exception:
        logger.exception("Failed to send Telegram notification")
        return False


# ── public helpers ─────────────────────────────────────────────────────────────

def telegram_new_request(req_id: int, factory_name: str, item_name: str,
                          vendor: str, final_amount: float,
                          requested_by: str, urgent: bool) -> bool:
    urgent_tag = " ⚡ URGENT" if urgent else ""
    message = (
        f"📋 <b>New Purchase Request #{req_id}</b>{escape(urgent_tag)}\n"
        f"Factory : {escape(factory_name)}\n"
        f"Item    : {escape(item_name)}\n"
        f"Vendor  : {escape(vendor)}\n"
        f"Amount  : ₹{final_amount:,.2f}\n"
        f"By      : {escape(requested_by)}\n"
        f"Please review in the approval portal."
    )
    return _send(message)


def telegram_bill_upload(req_id: int, vendor_name: str, uploaded_by: str) -> bool:
    message = (
        f"🧾 <b>Bill Uploaded - Request #{req_id}</b>\n"
        f"Vendor  : {escape(vendor_name)}\n"
        f"By      : {escape(uploaded_by)}\n"
        f"Please review in the approval portal."
    )
    return _send(message)
