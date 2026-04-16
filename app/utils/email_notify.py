"""Email notification utility.

Configure via environment variables:
  NOTIFY_EMAIL      – recipient address that receives all alerts (required)
  SMTP_HOST         – SMTP server host           (default: smtp.gmail.com)
  SMTP_PORT         – SMTP server port           (default: 587)
  SMTP_USER         – SMTP login username        (required)
  SMTP_PASSWORD     – SMTP login password / app-password (required)
  SMTP_FROM         – From address               (defaults to SMTP_USER)
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# ── configuration ─────────────────────────────────────────────────────────────
NOTIFY_EMAIL   = os.getenv("NOTIFY_EMAIL", "")          # set this to your mail id
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER      = os.getenv("SMTP_USER", "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM      = os.getenv("SMTP_FROM", SMTP_USER)


def _send(subject: str, body_html: str) -> None:
    """Send an HTML email to NOTIFY_EMAIL. Logs and swallows errors silently."""
    if not NOTIFY_EMAIL:
        logger.warning("NOTIFY_EMAIL not set – skipping email notification")
        return
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP_USER / SMTP_PASSWORD not set – skipping email notification")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [NOTIFY_EMAIL], msg.as_string())
        logger.info("Email notification sent to %s | subject: %s", NOTIFY_EMAIL, subject)
    except Exception:
        logger.exception("Failed to send email notification")


# ── public helpers ─────────────────────────────────────────────────────────────

def notify_new_request(req_id: int, factory_name: str, item_name: str,
                        vendor: str, final_amount: float, requested_by: str,
                        urgent: bool) -> None:
    urgent_badge = "<span style='color:red;font-weight:bold'> ⚡ URGENT</span>" if urgent else ""
    subject = f"[Payment Approval] New Request #{req_id}{' – URGENT' if urgent else ''}"
    body = f"""
<h3>New Purchase Request Submitted{urgent_badge}</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif">
  <tr><th align="left">Request #</th><td>{req_id}</td></tr>
  <tr><th align="left">Factory</th><td>{factory_name}</td></tr>
  <tr><th align="left">Item</th><td>{item_name}</td></tr>
  <tr><th align="left">Vendor</th><td>{vendor}</td></tr>
  <tr><th align="left">Amount (incl GST)</th><td>₹{final_amount:,.2f}</td></tr>
  <tr><th align="left">Requested By</th><td>{requested_by}</td></tr>
</table>
<p>Please log in to the approval portal to review this request.</p>
"""
    _send(subject, body)


def notify_bill_upload(req_id: int, vendor_name: str, uploaded_by: str) -> None:
    subject = f"[Payment Approval] Bill Uploaded – Request #{req_id}"
    body = f"""
<h3>A Bill Has Been Uploaded</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif">
  <tr><th align="left">Request #</th><td>{req_id}</td></tr>
  <tr><th align="left">Vendor</th><td>{vendor_name}</td></tr>
  <tr><th align="left">Uploaded By</th><td>{uploaded_by}</td></tr>
</table>
<p>Please log in to the approval portal to review the bill.</p>
"""
    _send(subject, body)
