"""
Storefront webhook receiver — the production ingestion path.

A real Shopify store registers `checkouts/abandoned` to POST here; WooCommerce,
BigCommerce, or a custom storefront would POST the same kind of payload to their
own route. Each handler normalizes to our `abandoned_carts` schema via
ingest.shopify, after which the agent pipeline treats every cart identically.

The Streamlit dashboard's "Inject test abandoned cart" button calls the same
ingest function directly, so you can demo ingestion without a public callback URL.

Run:
    venv/Scripts/python.exe webhook_server.py      # listens on :8000
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from flask import Flask, request, jsonify

from ingest.shopify import parse_shopify_abandoned_checkout, ingest_abandoned_cart, simulate_incoming_cart

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/webhook/shopify/checkouts-abandoned")
def shopify_abandoned():
    """Receive a Shopify `checkouts/abandoned` webhook and store it as a recovery opportunity.

    In production you'd also verify the `X-Shopify-Hmac-SHA256` signature here.
    """
    payload = request.get_json(force=True, silent=True) or {}
    if not payload:
        return jsonify(error="empty or invalid JSON payload"), 400
    try:
        cart = ingest_abandoned_cart(parse_shopify_abandoned_checkout(payload))
        return jsonify(
            status="ingested",
            cart_id=cart["cart_id"],
            customer_id=cart["customer_id"],
            cart_value=cart["cart_value"],
            items=[i["product_id"] for i in cart["items"]],
        ), 201
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.post("/webhook/simulate")
def simulate():
    """Convenience endpoint: synthesize + ingest one realistic abandoned cart."""
    cart = simulate_incoming_cart()
    return jsonify(status="ingested", cart_id=cart["cart_id"],
                   customer_id=cart["customer_id"], cart_value=cart["cart_value"]), 201


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
