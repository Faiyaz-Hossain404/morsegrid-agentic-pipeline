"""
Pluggable ecommerce cart ingestion.

`parse_shopify_abandoned_checkout` maps a real Shopify `checkouts/abandoned`
webhook payload onto our `abandoned_carts` schema. The same normalized shape
would come from WooCommerce, BigCommerce, or a custom storefront — only the
parser changes, so the agent pipeline is storefront-agnostic.

For the demo, `simulate_incoming_cart` synthesizes a realistic Shopify payload
for an existing customer and ingests it, so you can watch a brand-new abandoned
cart appear in the queue on the next Planner run.

Ingestion is a storefront-side ETL action (not an agent action), so it uses
pymongo — consistent with how seeding/indexing work. The agents read these
carts at runtime through the MongoDB MCP server.
"""
import os
import sys
import random
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from db.mongo import get_db_client

DB_NAME = "morsegrid_outfitters"


def _catalog(db):
    return {p["product_id"]: p for p in db.products.find(
        {}, {"product_id": 1, "title": 1, "price": 1, "in_stock": 1, "_id": 0})}


def parse_shopify_abandoned_checkout(payload: dict) -> dict:
    """Normalize a Shopify `checkouts/abandoned` payload to our cart schema.

    We key line items on SKU (Shopify merchants set SKU = our product_id).
    """
    line_items = payload.get("line_items", []) or []
    items = []
    for li in line_items:
        items.append({
            "product_id": li.get("sku") or str(li.get("product_id", "")),
            "title":      li.get("title", ""),
            "price":      float(li.get("price", 0) or 0),
            "qty":        int(li.get("quantity", 1) or 1),
            "in_stock_now": True,  # resolved against our catalog at ingest time
        })
    cart_value = round(sum(i["price"] * i["qty"] for i in items), 2)
    if not cart_value:
        cart_value = float(payload.get("total_price", 0) or 0)

    cust = payload.get("customer") or {}
    created = payload.get("created_at")
    try:
        created_at = (datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                      if created else datetime.now(timezone.utc))
    except Exception:
        created_at = datetime.now(timezone.utc)

    return {
        "cart_id":         payload.get("token") or f"CART-{payload.get('id', 'UNKNOWN')}",
        "customer_id":     cust.get("external_id") or payload.get("customer_id"),
        "source":          "shopify",
        # A Shopify "abandoned checkout" means they entered checkout, so default
        # to that stage unless the merchant tagged a further step.
        "stage":           payload.get("_stage", "checkout_started"),
        "items":           items,
        "cart_value":      cart_value,
        "currency":        payload.get("currency", "USD"),
        "created_at":      created_at,
        "checkout_url":    payload.get("abandoned_checkout_url", ""),
        "recovered":       False,
        "recovery_status": "pending",
    }


def ingest_abandoned_cart(cart_doc: dict, db=None) -> dict:
    """Resolve item stock/titles against the catalog and upsert the cart."""
    client = get_db_client()
    db = db or client[DB_NAME]
    cat = _catalog(db)

    for it in cart_doc.get("items", []):
        prod = cat.get(it.get("product_id"))
        if prod:
            it["in_stock_now"] = bool(prod.get("in_stock", True))
            it.setdefault("title", prod.get("title", ""))
            if not it.get("price"):
                it["price"] = float(prod.get("price", 0))

    db.abandoned_carts.update_one(
        {"cart_id": cart_doc["cart_id"]},
        {"$set": cart_doc},
        upsert=True,
    )
    return cart_doc


def build_sample_shopify_payload(customer_id: str, customer_name: str,
                                 product_ids: list, db) -> dict:
    """Construct a payload shaped like a real Shopify `checkouts/abandoned` webhook."""
    cat = _catalog(db)
    token = f"CART-WH-{datetime.now(timezone.utc).strftime('%H%M%S')}{random.randint(10, 99)}"
    line_items = []
    for pid in product_ids:
        prod = cat.get(pid, {})
        line_items.append({
            "sku":        pid,
            "product_id": random.randint(10_000_000, 99_999_999),  # Shopify's own numeric id
            "title":      prod.get("title", pid),
            "price":      str(prod.get("price", 0)),
            "quantity":   1,
        })
    return {
        "id":   random.randint(100_000_000, 999_999_999),
        "token": token,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "currency": "USD",
        "abandoned_checkout_url": f"https://morsegrid-demo.myshopify.com/checkout/{token}",
        "customer": {"external_id": customer_id, "first_name": customer_name.split()[0]},
        "line_items": line_items,
        "total_price": str(sum(float(li["price"]) for li in line_items)),
    }


def simulate_incoming_cart() -> dict:
    """Pick an existing customer + in-stock products, emit a Shopify-shaped payload,
    parse it, and ingest. Returns the stored cart document."""
    client = get_db_client()
    db = client[DB_NAME]

    customers = list(db.customers.find({}, {"customer_id": 1, "name": 1, "_id": 0}))
    open_cart_ids = {c["customer_id"] for c in db.abandoned_carts.find(
        {"recovered": {"$ne": True}}, {"customer_id": 1, "_id": 0})}
    candidates = [c for c in customers if c["customer_id"] not in open_cart_ids] or customers
    cust = random.choice(candidates)

    in_stock = [p["product_id"] for p in db.products.find({"in_stock": True}, {"product_id": 1, "_id": 0})]
    pids = random.sample(in_stock, k=random.choice([1, 1, 2]))

    payload = build_sample_shopify_payload(cust["customer_id"], cust["name"], pids, db)
    cart_doc = parse_shopify_abandoned_checkout(payload)
    # vary the funnel stage + recency a little so the queue stays interesting
    cart_doc["stage"] = random.choice(["cart", "checkout_started", "payment_info"])
    cart_doc["created_at"] = datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 30))
    return ingest_abandoned_cart(cart_doc, db)


if __name__ == "__main__":
    cart = simulate_incoming_cart()
    print(f"Ingested {cart['cart_id']} for {cart['customer_id']}: "
          f"{[i['product_id'] for i in cart['items']]} = ${cart['cart_value']:.0f} ({cart['stage']})")
