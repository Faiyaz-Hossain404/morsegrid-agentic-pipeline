import math

# How far down the funnel the shopper got -> base probability we can win them back.
# Reaching the payment step signals far more intent than a bare cart add.
STAGE_BASE_P = {
    "payment_info":     0.30,
    "checkout_started": 0.20,
    "cart":             0.12,
}

MARGIN_RATIO = 0.35  # ~35% gross margin on motorcycle gear (matches lead_scorer)


def score_cart_recovery_ev(
    cart_id: str,
    cart_value: float,
    hours_since_abandon: float,
    stage: str,
    email_opens_last_30d: int = 0,
    sms_opted_in: bool = False,
    item_in_stock: bool = True,
) -> dict:
    """
    Expected value of recovering one abandoned cart, in expected-recovered-margin dollars.

        score = P(recover) x (cart_value x margin) x recency_factor

    Carts decay fast: recency uses an ~3-day half-life, so the first hours are
    worth the most. The score is directly comparable to the dormant lead EV
    (lead_scorer.score_lead_ev), so both opportunity types share one ranked queue.

    Args:
        cart_id: Abandoned cart identifier.
        cart_value: Total cart value in USD.
        hours_since_abandon: Hours elapsed since the cart was abandoned.
        stage: Funnel stage at abandon — "cart", "checkout_started", or "payment_info".
        email_opens_last_30d: Emails opened in the last 30 days (0-5).
        sms_opted_in: Whether the customer accepts SMS (gives a reachable backup channel).
        item_in_stock: False if the abandoned item has since sold out (lowers direct recovery).

    Returns:
        Dict: cart_id, score, p_recover, recoverable_value, recency_factor,
        hours_since_abandon, rationale.
    """
    base_p = STAGE_BASE_P.get(stage, 0.12)

    # Engagement signal: a reachable, responsive shopper is easier to win back.
    if email_opens_last_30d >= 2:
        base_p = min(base_p * 1.25, 0.75)
    elif email_opens_last_30d == 0 and sms_opted_in:
        base_p = min(base_p * 1.10, 0.75)  # email-dead but SMS-reachable

    # Sold-out item dampens *direct* recovery (we must pivot to alternatives).
    if not item_in_stock:
        base_p *= 0.80

    p_recover = round(base_p, 3)

    recoverable_value = round(cart_value * MARGIN_RATIO, 2)

    # ~3-day half-life: exp(-hours / 104) ~= 0.5 at 72h.
    recency_factor = round(math.exp(-max(hours_since_abandon, 0) / 104.0), 3)

    score = round(p_recover * recoverable_value * recency_factor, 2)

    notes = [f"{stage.replace('_', ' ')} stage"]
    if hours_since_abandon <= 6:
        notes.append("abandoned <6h ago — act now")
    elif hours_since_abandon >= 24:
        notes.append(f"{int(hours_since_abandon)}h cold")
    if not item_in_stock:
        notes.append("item sold out — needs alternatives")
    if email_opens_last_30d == 0 and sms_opted_in:
        notes.append("email cold — SMS reachable")
    if cart_value >= 500:
        notes.append("high-value cart")

    rationale = (f"P(recover)={p_recover:.0%}, recoverable=${recoverable_value:.0f}, "
                 f"recency={recency_factor:.2f}")
    if notes:
        rationale += " | " + "; ".join(notes)

    return {
        "cart_id": cart_id,
        "score": score,
        "p_recover": p_recover,
        "recoverable_value": recoverable_value,
        "recency_factor": recency_factor,
        "hours_since_abandon": round(hours_since_abandon, 1),
        "rationale": rationale,
    }
