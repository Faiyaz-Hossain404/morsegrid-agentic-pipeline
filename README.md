# Morsegrid Outfitters — AI Revenue Recovery Agent

> A multi-agent system that recovers lost ecommerce revenue from **two** sources at once:
> **abandoned carts** and **dormant customers**. Built for the Google Cloud **Rapid Agent
> Hackathon** — **MongoDB partner track**.

**Live app:** https://morsegrid-recovery-839289631541.us-central1.run.app &nbsp;·&nbsp; **Demo video:** `<YOUTUBE_URL>`

---

## What it does

Most stores fire the *same* templated email at everyone. This system instead deploys
**three cooperating Gemini 3 agents** that *reason* over each shopper's full history and
the live product catalog — pulled from **MongoDB via the MongoDB MCP server** — to decide
**who** to contact, **what** to say, and **which channel** to use, with a human approving
every send.

It handles two kinds of money left on the table through one pipeline:

| Mode | Trigger | What the agent does |
|------|---------|---------------------|
| 🛒 **Abandoned cart recovery** | A `checkouts/abandoned` webhook (Shopify or any store) | Reasons over the abandoned session — reassures about the exact item, suggests **in-stock alternatives** if it sold out, or **completes the look** for multi-item carts |
| 💤 **Dormant re-engagement** | A lapsed customer with matching new inventory | Warm win-back tied to a real reason: a new arrival matching their history, or the exact thing they once searched for is finally in stock |

Both opportunity types are scored in **expected-recovered-margin dollars** and ranked in a
single queue, so the most valuable recovery — whichever kind — rises to the top.

---

## Why it fits the tracks

**MongoDB partner track — the integration is the linchpin.** Every *runtime* database
operation the agents perform goes through the **MongoDB MCP server** (`find`, `aggregate`,
`count`, `insert-many`) — never raw drivers. Product matching uses **Atlas Vector Search**
(`$vectorSearch`) over `text-embedding-004` embeddings. Offline seeding/indexing uses
pymongo (dev-time ETL), but the agent's superpowers come exclusively from MCP.

**Google Cloud.** Agents are built with the **Agent Development Kit (ADK)** — the code-first
path of Google Cloud's Agent Builder — and reason with **Gemini 3 Flash** on **Vertex AI**.
Embeddings use Vertex `text-embedding-004`. The app is deployed on **Cloud Run**.

---

## Architecture

```
  Shopify / WooCommerce / custom store
        │  checkouts/abandoned  (webhook_server.py  →  ingest/shopify.py)
        ▼
   ┌──────────────── MongoDB Atlas ────────────────┐
   │ customers · products · behavior_events ·       │
   │ orders · abandoned_carts · messages_sent       │
   │   + vector indexes (products, customers)       │
   └───────────────────────▲────────────────────────┘
                            │  ALL agent DB access via ↓
                 ┌──────────────────────────┐
                 │   MongoDB MCP Server      │  ← partner integration
                 │   find · aggregate ·      │
                 │   count · insert-many     │
                 └──────────▲───────────────┘
                            │ (ADK McpToolset, stdio)
   ╔════════════════════════╪═══════════════════════════════╗
   ║   ADK multi-agent app        model: GEMINI 3 FLASH      ║
   ║                                                          ║
   ║   PLANNER ───────►  NURTURER ───────►  SENDER            ║
   ║   (rank carts +     (read history,     (pick channel,    ║
   ║    dormant by EV)    vector-match,      send, log)       ║
   ║                      draft message)                      ║
   ║       │                  │                  │            ║
   ║   cart_scorer       find_similar_      pick_channel      ║
   ║   lead_scorer        products (Atlas)   send_email/sms   ║
   ╚════════════════════════╪═══════════════════════════════╝
                            ▼
                  Streamlit dashboard  (human-in-the-loop:
                  inspect MCP trace · edit draft · approve/reject)
```

- **Planner** (`planner.py`) — deterministic Python scoring (no LLM, to save quota): ranks
  abandoned carts (`P(recover) × cart_value × recency`) and dormant customers
  (`P(convert) × margin × recency`) in one comparable, sorted queue.
- **Nurturer** (Gemini 3 + ADK + MCP) — `find`s the shopper's behavior events, runs Atlas
  Vector Search for the right products, and drafts a strategy-aware personalized message.
- **Sender** — picks the channel from engagement signals (email / SMS / IG DM), delivers
  (real email via Resend; SMS/IG mocked + labeled), and logs the result to MongoDB.
- **Human-in-the-loop** — the Streamlit dashboard shows every MCP tool call; you edit and
  approve or reject before anything is sent.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Reasoning | **Gemini 3 Flash** (Vertex AI) |
| Agent framework | **Google ADK** (Agent Builder, code-first) |
| Database ops (runtime) | **MongoDB MCP Server** |
| Semantic search | **MongoDB Atlas Vector Search** + Vertex `text-embedding-004` |
| Cart ingestion | Shopify-style webhook (`webhook_server.py`) → pluggable parser |
| Email delivery | Resend API (real) · SMS/IG mocked |
| UI | Streamlit (human-in-the-loop) |
| Hosting | **Google Cloud Run** |

---

## Demo scenarios

| Shopper | Mode | The "wow" |
|---------|------|-----------|
| **Mike** (C001) | 🛒 Cart | Left a **$599 carbon helmet at the payment step** 3h ago → AI reassures about that exact item |
| **Sarah** (C002) | 🛒 Cart | $700 two-item cart; **0/5 emails opened** → Sender **switches to SMS** |
| **Diego** (C003) | 🛒 Cart | Cart item **sold out** → vector search suggests in-stock alternatives |
| **Ava** (C004) | 💤 Re-engage | VIP quiet 78 days → win-back tied to a new arrival matching her history |
| **Marcus** (C005) | 💤 Re-engage | Searched "cafe racer jacket" long ago, none then → it's in stock now |

---

## Run it locally

Prerequisites: Python 3.12+, Node.js 18+ (for the MCP server), a MongoDB Atlas cluster,
a Google Cloud project with Vertex AI enabled (`gcloud auth application-default login`),
and a Resend API key.

```powershell
# 1. Install deps
python -m venv venv; venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configure .env  (see .env.example)

# 3. Seed + embed (one-time)
python data\seed_data.py
python data\build_index.py

# 4a. Dashboard (recommended for the demo)
streamlit run dashboard.py

# 4b. or headless pipeline
python run_pipeline.py

# 4c. or the webhook receiver
python webhook_server.py    # POST a Shopify checkouts/abandoned payload to :8000
```

## Deploy to Cloud Run

```powershell
gcloud run deploy morsegrid-recovery --source . --region us-central1 `
  --allow-unauthenticated --memory 2Gi --cpu 2 `
  --min-instances 1 --max-instances 1 --timeout 3600 `
  --env-vars-file .env.yaml
```

The image (`Dockerfile`) ships both Python and Node.js so the MongoDB MCP server runs
in-container. The Cloud Run service account needs `roles/aiplatform.user`, and Atlas
Network Access must allow the service (e.g. `0.0.0.0/0` for the demo).

---

## Data model (MongoDB)

`customers` · `products` (+ `desc_vector`) · `behavior_events`
(`view`/`search`/`cart_add`/`checkout_start`/`cart_abandon`/`order`/`email_*`) ·
`orders` · **`abandoned_carts`** (cart_id, items, cart_value, stage, source, recovery_status) ·
`messages_sent` (delivery log).

## License

MIT — see [LICENSE](LICENSE).
