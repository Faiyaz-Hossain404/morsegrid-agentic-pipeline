import math


def score_lead_ev(
    customer_id: str,
    segment: str,
    days_inactive: int,
    total_orders: int,
    avg_order_value: float,
    email_opens_last_30d: int,
    sms_opted_in: bool,
) -> dict:
    """
    Calculate the Expected Value score for re-engaging a customer.
    Call this for every customer to determine re-engagement priority.

    Args:
        customer_id: The customer's ID string.
        segment: Customer segment — VIP, engaged, repeat, one-time, cart-abandoner, dormant_email, cold.
        days_inactive: Days since the customer's last order or active session.
        total_orders: Total number of orders placed lifetime.
        avg_order_value: Average order value in USD. Pass 250.0 if no orders yet.
        email_opens_last_30d: Number of emails opened in the last 30 days (0-5).
        sms_opted_in: Whether the customer has opted into SMS marketing.

    Returns:
        Dict with keys: customer_id, score, p_convert, margin_est, recency_factor, rationale.
        Higher score = higher priority to contact today.
    """
    base_p = {
        "VIP": 0.45,
        "engaged": 0.40,
        "repeat": 0.30,
        "one-time": 0.15,
        "cart-abandoner": 0.35,
        "dormant_email": 0.10,
        "cold": 0.05,
    }.get(segment, 0.10)

    if email_opens_last_30d >= 3:
        base_p = min(base_p * 1.3, 0.70)
    elif email_opens_last_30d == 0 and sms_opted_in:
        base_p = min(base_p * 1.15, 0.70)

    p_convert = round(base_p, 3)

    # 35% gross margin on motorcycle gear
    margin_est = round(avg_order_value * 0.35, 2) if avg_order_value > 0 else 87.50

    # Exponential recency decay, half-life ~60 days
    recency_factor = round(math.exp(-days_inactive / 60), 3)

    score = round(p_convert * margin_est * recency_factor, 2)

    notes = []
    if segment in ("VIP", "engaged"):
        notes.append("high-value segment")
    if email_opens_last_30d >= 3:
        notes.append(f"{email_opens_last_30d} email opens in last 30d")
    if email_opens_last_30d == 0 and sms_opted_in:
        notes.append("email cold — SMS opt-in active")
    if days_inactive < 7:
        notes.append("very recently active")
    if total_orders >= 3:
        notes.append(f"{total_orders} prior orders")

    rationale = f"P(convert)={p_convert:.0%}, margin=${margin_est:.0f}, recency={recency_factor:.2f}"
    if notes:
        rationale += " | " + "; ".join(notes)

    return {
        "customer_id": customer_id,
        "score": score,
        "p_convert": p_convert,
        "margin_est": margin_est,
        "recency_factor": recency_factor,
        "rationale": rationale,
    }
