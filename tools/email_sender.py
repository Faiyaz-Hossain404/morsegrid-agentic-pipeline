import os
import re
import sys
import base64
import html as _html
from email.mime.text import MIMEText

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _style_inline(text: str) -> str:
    """Escape text, then re-apply emphasis: **bold** markers and any $price."""
    safe = _html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)          # **bold**
    safe = re.sub(r"(\$\d[\d,]*(?:\.\d{2})?)", r"<strong>\1</strong>", safe)  # $599 etc.
    return safe


def _build_html_body(body: str) -> str:
    """Render the plain-text body into a branded, styled HTML email."""
    store_url = os.getenv("STORE_URL", "https://morsegrid-outfitters.com")
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    inner = "".join(
        f"<p style=\"margin:0 0 16px 0\">{_style_inline(p).replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
    return f"""\
<div style="background:#f4f4f5;padding:24px 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e4e4e7;">
    <div style="background:#0f172a;padding:22px 30px;">
      <div style="color:#ffffff;font-size:19px;font-weight:800;letter-spacing:1.5px;">MORSEGRID OUTFITTERS</div>
      <div style="color:#22c55e;font-size:11px;letter-spacing:2.5px;text-transform:uppercase;margin-top:3px;">Premium Motorcycle Gear</div>
    </div>
    <div style="padding:30px;color:#27272a;font-size:15px;line-height:1.65;">
      {inner}
      <div style="margin:26px 0 6px;">
        <a href="{store_url}" style="display:inline-block;background:#22c55e;color:#0f172a;font-weight:700;text-decoration:none;padding:13px 26px;border-radius:8px;font-size:15px;">Complete Your Order &rarr;</a>
      </div>
    </div>
    <div style="padding:16px 30px;background:#fafafa;border-top:1px solid #eee;color:#a1a1aa;font-size:12px;line-height:1.5;">
      You're receiving this because you shopped with Morsegrid Outfitters.<br>
      Morsegrid Outfitters &middot; Ride ready.
    </div>
  </div>
</div>"""


def send_email_resend(
    to_email: str,
    subject: str,
    body: str,
    customer_id: str,
) -> dict:
    """
    Send a real transactional email via the Resend API.
    Use this tool when the chosen channel is "email".

    Args:
        to_email: The customer's email address (from their profile).
        subject: The email subject line.
        body: The email body text (plain text; will be converted to HTML for delivery).
        customer_id: The customer's ID, for logging purposes.

    Returns:
        Dict with keys: status ("sent" or "error"), message_id, to, customer_id.
    """
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    demo_to = os.getenv("DEMO_TO_EMAIL")

    if not api_key:
        return {"status": "error", "error": "RESEND_API_KEY not set", "customer_id": customer_id}

    actual_to = demo_to if demo_to else to_email
    html_body = _build_html_body(body)

    payload = {
        "from": from_email,
        "to": [actual_to],
        "subject": subject,
        "html": html_body,
        "reply_to": to_email,
    }

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        data = resp.json()
        if resp.status_code in (200, 201):
            return {
                "status": "sent",
                "message_id": data.get("id", "unknown"),
                "to": actual_to,
                "customer_id": customer_id,
            }
        return {
            "status": "error",
            "error": data.get("message", str(data)),
            "http_status": resp.status_code,
            "customer_id": customer_id,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "customer_id": customer_id}


def send_email_gmail(
    to_email: str,
    subject: str,
    body: str,
    customer_id: str,
) -> dict:
    """
    Send a real email through the Gmail API as the authenticated Google account.
    Drop-in alternative to send_email_resend; use this when the chosen channel is
    "email" and you want it sent from your own Gmail rather than Resend.

    Requires one-time OAuth setup — see google_services.py. Honors DEMO_TO_EMAIL
    the same way as the Resend sender (redirects all mail to the demo inbox when set).

    Args:
        to_email: The customer's email address (from their profile).
        subject: The email subject line.
        body: The email body text (plain text; converted to HTML for delivery).
        customer_id: The customer's ID, for logging purposes.

    Returns:
        Dict with keys: status ("sent" or "error"), message_id, to, customer_id.
    """
    demo_to = os.getenv("DEMO_TO_EMAIL")
    actual_to = demo_to if demo_to else to_email

    try:
        from google_services import gmail  # lazy: only needed when this sender runs

        msg = MIMEText(_build_html_body(body), "html")
        msg["To"] = actual_to
        msg["Subject"] = subject
        msg["Reply-To"] = to_email
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        sent = gmail().users().messages().send(userId="me", body={"raw": raw}).execute()
        return {
            "status": "sent",
            "message_id": sent.get("id", "unknown"),
            "to": actual_to,
            "customer_id": customer_id,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "customer_id": customer_id}
