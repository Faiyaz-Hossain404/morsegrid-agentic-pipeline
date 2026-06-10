"""
Unified opportunity Planner — the first phase of the Revenue Recovery pipeline.

Produces ONE ranked queue mixing two kinds of money-left-on-the-table:
  * abandoned_cart  — from `abandoned_carts` (scored by cart value x intent x recency)
  * dormant         — from `customers`        (scored by the lapsed-customer EV formula)

Scoring is deterministic Python so we don't burn Gemini quota ranking dozens of
records; the Nurturer and Sender agents still touch MongoDB exclusively via the
MongoDB MCP server. Both scorers return expected-margin dollars, so the two
opportunity types are directly comparable in a single sorted queue.
"""
from datetime import datetime, timezone

from db.mongo import get_db_client
from tools.lead_scorer import score_lead_ev
from tools.cart_scorer import score_cart_recovery_ev

DB_NAME = "morsegrid_outfitters"


def _as_aware(ts) -> datetime:
    now = datetime.now(timezone.utc)
    try:
        if isinstance(ts, datetime):
            return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return now


def _email_opens(cust: dict) -> int:
    eng = cust.get("engagement") or {}
    return sum(1 for v in (eng.get("last5_opens") or []) if v)


def build_opportunity_queue(db_name: str = DB_NAME) -> list:
    """Return all open recovery opportunities (cart + dormant), highest EV first."""
    client = get_db_client()
    db = client[db_name]
    now = datetime.now(timezone.utc)

    customers = {c["customer_id"]: c for c in db.customers.find({})}
    carts = list(db.abandoned_carts.find({"recovered": {"$ne": True}}))

    opps = []
    cart_customer_ids = set()

    # ---- Abandoned-cart opportunities ----
    for cart in carts:
        cid = cart["customer_id"]
        cart_customer_ids.add(cid)
        cust = customers.get(cid, {})
        eng = cust.get("engagement") or {}
        opens = _email_opens(cust)
        sms_optin = bool(eng.get("sms_optin", False))
        hours = max((now - _as_aware(cart.get("created_at"))).total_seconds() / 3600.0, 0.0)
        items = cart.get("items", [])
        items_in_stock = all(i.get("in_stock_now", True) for i in items) if items else True

        ev = score_cart_recovery_ev(
            cart_id=cart.get("cart_id", "?"),
            cart_value=float(cart.get("cart_value", 0.0)),
            hours_since_abandon=hours,
            stage=cart.get("stage", "cart"),
            email_opens_last_30d=opens,
            sms_opted_in=sms_optin,
            item_in_stock=items_in_stock,
        )

        opps.append({
            "opp_type":             "abandoned_cart",
            "customer_id":          cid,
            "name":                 cust.get("name", cid),
            "email":                cust.get("email", ""),
            "phone":                cust.get("phone", ""),
            "ig_handle":            cust.get("ig_handle", ""),
            "segment":              cust.get("segment", "cart-abandoner"),
            "score":                ev["score"],
            "rationale":            ev["rationale"],
            "p_value":              ev["p_recover"],
            "behavior_summary":     cust.get("behavior_summary", ""),
            "email_opens_last_30d": opens,
            "sms_opted_in":         sms_optin,
            # cart-specific
            "cart_id":              cart.get("cart_id"),
            "cart_value":           float(cart.get("cart_value", 0.0)),
            "cart_items":           items,
            "cart_stage":           cart.get("stage", "cart"),
            "hours_since_abandon":  ev["hours_since_abandon"],
            "items_in_stock":       items_in_stock,
            "cart_note":            cart.get("note", ""),
        })

    # ---- Dormant re-engagement opportunities (customers without an open cart) ----
    for cid, c in customers.items():
        if cid in cart_customer_ids:
            continue
        last_active = _as_aware(c.get("last_active_at"))
        days_inactive = max((now - last_active).days, 0)
        total_orders = int(c.get("total_orders", 0))
        total_spend = float(c.get("total_spend", 0.0))
        avg_order_val = (total_spend / total_orders) if total_orders > 0 else 250.0
        opens = _email_opens(c)
        sms_optin = bool((c.get("engagement") or {}).get("sms_optin", False))

        ev = score_lead_ev(
            customer_id=cid,
            segment=c.get("segment", "cold"),
            days_inactive=days_inactive,
            total_orders=total_orders,
            avg_order_value=avg_order_val,
            email_opens_last_30d=opens,
            sms_opted_in=sms_optin,
        )

        opps.append({
            "opp_type":             "dormant",
            "customer_id":          cid,
            "name":                 c.get("name", cid),
            "email":                c.get("email", ""),
            "phone":                c.get("phone", ""),
            "ig_handle":            c.get("ig_handle", ""),
            "segment":              c.get("segment", "cold"),
            "score":                ev["score"],
            "rationale":            ev["rationale"],
            "p_value":              ev["p_convert"],
            "behavior_summary":     c.get("behavior_summary", ""),
            "email_opens_last_30d": opens,
            "sms_opted_in":         sms_optin,
            # dormant-specific
            "days_inactive":        days_inactive,
            "total_orders":         total_orders,
            "total_spend":          total_spend,
        })

    return sorted(opps, key=lambda x: x["score"], reverse=True)
