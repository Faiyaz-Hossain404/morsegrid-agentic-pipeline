def pick_channel(
    segment: str,
    email_opens_last_30d: int,
    sms_opted_in: bool,
    ig_follower: bool = False,
) -> dict:
    """
    Choose the best outreach channel for a customer based on their engagement signals.

    Args:
        segment: Customer segment (VIP, engaged, repeat, one-time, cart-abandoner, dormant_email, cold).
        email_opens_last_30d: Number of emails this customer opened in the last 30 days.
        sms_opted_in: True if the customer has opted into SMS marketing.
        ig_follower: True if the customer follows the store on Instagram (optional).

    Returns:
        Dict with keys: channel ("email", "sms", or "ig_dm") and reason (explanation string).
    """
    if email_opens_last_30d >= 2:
        return {
            "channel": "email",
            "reason": f"Email responsive — {email_opens_last_30d} opens in last 30d",
        }

    if email_opens_last_30d == 0 and sms_opted_in:
        return {
            "channel": "sms",
            "reason": "Email cold (0 opens in 30d); SMS opt-in is active — higher chance of read",
        }

    if ig_follower:
        return {
            "channel": "ig_dm",
            "reason": "Email cold and no SMS opt-in; Instagram DM as last-resort channel",
        }

    # Default: email is still cheapest and leaves a paper trail
    return {
        "channel": "email",
        "reason": "No strong alternative signal — defaulting to email",
    }
