def send_sms_mock(
    to_phone: str,
    body: str,
    customer_id: str,
) -> dict:
    """
    Mock SMS send (Twilio not wired in demo). Logs the SMS that would be sent.
    Use this tool when the chosen channel is "sms".

    Args:
        to_phone: The customer's phone number (E.164 format, e.g. +15551234567).
        body: The SMS message body (keep under 160 chars for single segment).
        customer_id: The customer's ID, for logging purposes.

    Returns:
        Mock confirmation dict with status "mock_sent".
    """
    preview = body[:160] + ("..." if len(body) > 160 else "")
    print(f"  [MOCK SMS] To: {to_phone} | {preview}")
    return {
        "status": "mock_sent",
        "channel": "sms",
        "to": to_phone,
        "customer_id": customer_id,
        "body_preview": preview,
    }


def send_ig_dm_mock(
    ig_handle: str,
    body: str,
    customer_id: str,
) -> dict:
    """
    Mock Instagram DM send (Meta API not wired in demo). Logs the DM that would be sent.
    Use this tool when the chosen channel is "ig_dm".

    Args:
        ig_handle: The customer's Instagram handle (e.g. @username).
        body: The DM body text.
        customer_id: The customer's ID, for logging purposes.

    Returns:
        Mock confirmation dict with status "mock_sent".
    """
    preview = body[:200] + ("..." if len(body) > 200 else "")
    print(f"  [MOCK IG DM] To: {ig_handle} | {preview}")
    return {
        "status": "mock_sent",
        "channel": "ig_dm",
        "to": ig_handle,
        "customer_id": customer_id,
        "body_preview": preview,
    }
