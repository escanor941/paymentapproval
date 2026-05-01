"""Telegram notification utility via Telegram Bot API (free).

Setup (one-time):
  1. Open Telegram and message @BotFather.
  2. Send /newbot, follow prompts → you receive a BOT_TOKEN.
  3. Start a chat with your new bot (send it any message).
  4. Call https://api.telegram.org/bot<BOT_TOKEN>/getUpdates in a browser
     and find your "id" inside the "chat" object → that is your CHAT_ID.

Configure via environment variables:
  TELEGRAM_BOT_TOKEN  – Token from BotFather  e.g. 123456:ABCdef...
    TELEGRAM_CHAT_ID    – Single chat id (backward compatible)
    TELEGRAM_CHAT_IDS   – Comma separated chat ids e.g. 987654321,-1001234567890
"""

import logging
import os
import urllib.request
import json
from html import escape

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS  = os.getenv("TELEGRAM_CHAT_IDS", "")

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _target_chat_ids() -> list[str]:
    """Resolve target chats from TELEGRAM_CHAT_IDS (preferred) or TELEGRAM_CHAT_ID."""
    raw_ids = TELEGRAM_CHAT_IDS or TELEGRAM_CHAT_ID
    if not raw_ids:
        return []
    # Support comma-separated values and ignore extra spaces/empty items.
    return [chat_id.strip() for chat_id in raw_ids.split(",") if chat_id.strip()]


def _send(message: str) -> bool:
    """Send a Telegram message to one or more Telegram chats and report success."""
    target_chats = _target_chat_ids()
    if not TELEGRAM_BOT_TOKEN or not target_chats:
        logger.warning(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID(S) must be set - skipping Telegram notification"
        )
        return False

    url = _BASE_URL.format(token=TELEGRAM_BOT_TOKEN)
    success_count = 0

    for chat_id in target_chats:
        payload = json.dumps({
            "chat_id":    chat_id,
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
            if status == 200 and response_body.get("ok"):
                success_count += 1
                logger.info("Telegram notification sent (HTTP %s) to chat %s", status, chat_id)
            else:
                logger.warning(
                    "Telegram notification failed for chat %s: HTTP %s | response=%s",
                    chat_id,
                    status,
                    response_body,
                )
        except Exception:
            logger.exception("Failed to send Telegram notification to chat %s", chat_id)

    if success_count == 0:
        return False
    if success_count < len(target_chats):
        logger.warning("Telegram notification partially delivered (%s/%s)", success_count, len(target_chats))
    return True


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
