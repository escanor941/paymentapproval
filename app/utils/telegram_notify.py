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
import urllib.error
import json
from html import escape

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _target_chat_ids() -> list[str]:
    """Resolve target chats from env vars at call time (not import time)."""
    raw_ids = os.getenv("TELEGRAM_CHAT_IDS", "") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not raw_ids:
        return []
    return [chat_id.strip() for chat_id in raw_ids.split(",") if chat_id.strip()]


def _send(message: str) -> bool:
    """Send a Telegram message to one or more Telegram chats and report success."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    target_chats = _target_chat_ids()
    print(f"[Telegram] _send called. token_set={bool(bot_token)}, chats={target_chats}", flush=True)
    if not bot_token or not target_chats:
        logger.warning(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID(S) must be set - skipping Telegram notification"
        )
        return False

    url = _BASE_URL.format(token=bot_token)
    success_count = 0
    plain_message = message.replace("<b>", "").replace("</b>", "")

    for chat_id in target_chats:
        html_payload = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        plain_payload = json.dumps({
            "chat_id": chat_id,
            "text": plain_message,
        }).encode()

        delivered = False
        for attempt_name, payload in (("html", html_payload), ("plain", plain_payload)):
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
                print(
                    f"[Telegram] chat={chat_id} attempt={attempt_name} HTTP={status} ok={response_body.get('ok')}",
                    flush=True,
                )
                if status == 200 and response_body.get("ok"):
                    success_count += 1
                    delivered = True
                    logger.info(
                        "Telegram notification sent (%s) (HTTP %s) to chat %s",
                        attempt_name,
                        status,
                        chat_id,
                    )
                    break
                logger.warning(
                    "Telegram notification failed (%s) for chat %s: HTTP %s | response=%s",
                    attempt_name,
                    chat_id,
                    status,
                    response_body,
                )
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode(errors="replace")
                except Exception:
                    pass
                logger.warning(
                    "Telegram HTTPError (%s) for chat %s: status=%s body=%s",
                    attempt_name,
                    chat_id,
                    exc.code,
                    body,
                )
                print(
                    f"[Telegram] chat={chat_id} attempt={attempt_name} HTTPError={exc.code} body={body}",
                    flush=True,
                )
            except Exception:
                logger.exception(
                    "Failed to send Telegram notification (%s) to chat %s",
                    attempt_name,
                    chat_id,
                )

        if not delivered:
            logger.warning("Telegram notification could not be delivered to chat %s after retries", chat_id)

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


def telegram_request_approved(
    req_id: int,
    factory_name: str,
    item_name: str,
    vendor: str,
    approved_amount: float,
    approved_by: str,
) -> bool:
    message = (
        f"✅ <b>Request Approved #{req_id}</b>\n"
        f"Factory : {escape(factory_name)}\n"
        f"Item    : {escape(item_name)}\n"
        f"Vendor  : {escape(vendor)}\n"
        f"Amount  : ₹{approved_amount:,.2f}\n"
        f"By      : {escape(approved_by)}"
    )
    return _send(message)
