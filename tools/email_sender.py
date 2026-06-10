import os
import sys
import base64
from email.mime.text import MIMEText

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _build_html_body(body: str) -> str:
    """Render plain-text body (blank-line-separated paragraphs) into styled HTML."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    inner_html = "".join(
        f"<p style='margin:0 0 14px 0'>{p.replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
    return (
        "<div style='font-family:sans-serif;font-size:15px;line-height:1.6;"
        "max-width:600px;margin:0 auto;padding:32px 24px;color:#222'>"
        + inner_html
        + "</div>"
    )


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
