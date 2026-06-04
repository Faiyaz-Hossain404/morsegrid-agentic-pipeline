# Morsegrid Outfitters — Ecommerce Re-engagement Agent
### Build Plan (start → submission)

> **Hackathon:** Google Cloud Rapid Agent Hackathon — **MongoDB Track**
> **Deadline:** **2026-06-11, 2:00 PM PT** (today: 2026-06-04 → ~7 days left)
> **Owners:** Maks (narrative + agent prompts + video) · Sifath (full-stack build + infra)
> **Repo:** `d:\hackathon\` (standalone git repo — no edits to Morsegrid production scripts)

---

## 1. What this is (one paragraph)

An **agent-based re-engagement system** for a demo motorcycle-gear store ("Morsegrid
Outfitters"). Instead of deterministic flows (Klaviyo/Postscript) that fire the same
template at everyone, three cooperating agents **reason across each customer's full
history + the product catalog + recency**, decide who to contact, draft a personalized
message, and pick the right channel. The wedge: *agent that reasons across history and
channels* — client-owned, not SaaS (Markopolo-style framing).

---

## 2. Locked scope decisions

| Decision | Choice | Why |
|---|---|---|
| **Build tier** | **Safe-ship multi-agent** | Highest odds of a finished, impressive submission in 7 days |
| **Agent protocol** | **Direct ADK agent-to-agent calls** (NOT the A2A protocol) | A2A kill-date (May 26) already passed; A2A is the riskiest, lowest-ROI integration. Stretch goal only if everything ships early |
| **Email** | **Real send** (SendGrid) | Proves a live channel; lands in a test inbox |
| **SMS / Instagram DM** | **Mocked in the UI** | Drafted message shown + labeled *"would send via Twilio / Meta API"*. Avoids Meta approval + Twilio verification delays |
| **ROI feature** | **EV-based lead ranking** | The Planner ranks by `P(convert) × margin × recency`, not vague "intent" — the visible "smart" behavior |
| **Dashboard** | **Live, hosted** | Shows agent reasoning, tool calls, channel decisions in real time |
| **Data** | **100% synthetic** | No real client data; ~18 customers, ~50 products, ~200 events |

**Deselected (optional fast-follows if time frees up):** margin-aware discount decisioning,
cart-abandonment hero scenario, holdout + "$ incremental revenue" readout. *Note: products
keep a `cost`/`margin` field anyway, so these can be added later with zero rework.*

### Honest framing (for the pitch)
This is **retention / re-engagement**, not strictly **CRO**. The demo proves *capability*
(the agent reasons + picks a channel). EV ranking is what makes it read as a *business*
decision rather than a chatbot. The single cheapest way to later prove *ROI* would be a
simulated holdout group with an incremental-revenue number — deferred for now.

---

## 3. Architecture

```
   Demo store (signup form + chat widget)
                │  POST lead / behavior event
                ▼
        Webhook  (server)  ──────────────► MongoDB Atlas
                │                            customers · behavior_events
                ▼                            products · orders · messages_sent
        ┌───────────────┐                    (+ vector indexes on
        │  PLANNER      │  decides WHO         desc_vector & behavior_vector)
        │  agent        │  → ranked queue            ▲
        └──────┬────────┘  (EV ranking)              │ tools read/write
               │ direct call (per lead)              │
        ┌──────▼────────┐                            │
        │  NURTURER     │  decides WHAT  ────────────┤ vector product match
        │  agent        │  → drafted message         │
        └──────┬────────┘                            │
               │ direct call                         │
        ┌──────▼────────┐                            │
        │  SENDER       │  decides CHANNEL ──────────┘
        │  agent        │  → email (real) / SMS·IG (mock) → log
        └──────┬────────┘
               ▼
        Live dashboard  (queue · reasoning trace · channel decision · send log)
```

Orchestration = ADK `SequentialAgent` (or plain Python runner calls): **Planner → Nurturer
→ Sender**. Every agent's tool calls + output are captured into an `agent_trace` — that
trace is the demo.

---

## 4. Data model (MongoDB — 5 collections)

```
customers
  _id, customer_id, name, email, phone, ig_handle, segment,
  total_orders, total_spend, created_at, last_active_at,
  engagement { open_rate, click_rate, sms_optin, last5_opens[bool] },
  behavior_summary (text)   ──embed──► behavior_vector [768]

behavior_events
  _id, customer_id, type, ts, product_id?, query?, metadata?
  type ∈ view | search | cart_add | cart_abandon | checkout_start |
         order | email_sent | email_open | email_click | chat

products
  _id, product_id, title, description, category, price, cost, margin,
  in_stock, tags[], created_at, restocked_at?
  (title+description+category+tags) ──embed──► desc_vector [768]

orders
  _id, customer_id, items[ {product_id, price, qty} ], total, ts

messages_sent
  _id, customer_id, channel, subject?, body, status (sent|mock|queued),
  reasoning, agent_trace, ts
```

**Vector indexes:** `768` dims, `cosine` similarity — on `products.desc_vector`
(`products_vector_index`) and `customers.behavior_vector` (`customers_vector_index`).

---

## 5. Components to build

| Module (responsibility) | Notes |
|---|---|
| **embeddings** | Wrap Vertex `text-embedding-004`. `RETRIEVAL_DOCUMENT` for stored docs, `RETRIEVAL_QUERY` for live queries. *(✅ base version already working)* |
| **db / mongo** | Atlas client + collection accessors + ping |
| **seed data** | Generate synthetic store, write to MongoDB (no vectors) |
| **build index** | Embed product + customer docs, write vectors, create vector indexes, verify query |
| **tools** | Deterministic functions the agents call (see §6) |
| **agents** | Planner / Nurturer / Sender + orchestrator (see §7) |
| **server** | Webhook: capture → trigger orchestrator; read API for dashboard |
| **dashboard** | Streamlit: queue, EV rationale, reasoning trace, channel decision, send log |
| **store** | Demo storefront page + signup form + chat widget |

*File layout (flat or foldered) is adjustable — TBD before coding.*

---

## 6. Tools (what the agents can call)

| Tool | Used by | Returns |
|---|---|---|
| `get_active_leads(limit)` | Planner | candidate customers needing nurture |
| `score_lead_ev(customer_id)` | Planner | `{score, p_convert, margin_est, recency_factor, rationale}` ← **EV ranking** |
| `get_customer_history(customer_id)` | Nurturer | orders + events + summary |
| `search_matching_products(query\|customer_id, k)` | Nurturer | top-k via `$vectorSearch` |
| `get_engagement_pattern(customer_id)` | Nurturer/Sender | open rate, best-channel hint |
| `pick_channel(customer_id)` | Sender | `email` \| `sms` \| `ig_dm` |
| `send_email(to, subject, body)` | Sender | **REAL** (SendGrid) |
| `send_sms(to, body)` / `send_ig_dm(handle, body)` | Sender | **MOCK** — log + return `"mock"` |
| `log_send(...)` | Sender | writes `messages_sent` (incl. reasoning + trace) |

---

## 7. Agents

- **Planner** — triggered on schedule or webhook. Calls `get_active_leads` then
  `score_lead_ev` per lead → returns a **ranked queue** (highest expected value first),
  each with a one-line rationale shown on the dashboard.
- **Nurturer** — per queued lead: `get_customer_history`, `search_matching_products`
  (vector), `get_engagement_pattern` → LLM drafts a contextual message + reasoning trace.
- **Sender** — `pick_channel` from engagement → `send_email` (real) or `send_sms`/
  `send_ig_dm` (mock) → `log_send`. Visibly explains the channel choice.

---

## 8. Demo scenarios (the 3 in the video)

1. **Cross-session memory + product match** — *Mike* asked (chat) about the Rallye
   Adventure Helmet ~2 months ago; it was out of stock. It's back in stock today. Planner
   queues him, Nurturer drafts referencing the original inquiry, Sender picks email.
2. **Channel switch** — *Sarah* browsed helmets but has opened 0 of her last 5 emails. A
   new helmet drops. Sender visibly decides *"email engagement low → switch to SMS."*
3. **Latent-want detection** — *Diego* searched "cafe racer jacket" 6 weeks ago; no match
   then. A new arrival now fits. Agent surfaces it and drafts a "we got what you were
   looking for" message.

---

## 9. Execution plan (day by day)

> Mark `[x]` as completed. Pass gate must be green before moving on.

### Day 1 · Jun 4–5 — Data layer
- [ ] `requirements.txt` (pin installed + add google-adk, sendgrid, streamlit)
- [ ] DB connection module + ping
- [ ] Seed script: ~18 customers, ~50 products (with cost+margin), ~200 events, orders
- [ ] Build-index script: embed product + customer docs, create both vector indexes
- [ ] **Pass gate:** `$vectorSearch` aggregate returns ≥1 hit on the products index

### Day 2 · Jun 6 — Tools
- [ ] All tools in §6, incl. `score_lead_ev` (EV ranking) and `search_matching_products`
- [ ] Real SendGrid `send_email`; mocked `send_sms` / `send_ig_dm`
- [ ] **Pass gate:** every tool callable + smoke-tested individually
- [ ] Verify `google-adk` installs/imports on Python 3.14 (risk — see §11)

### Day 3 · Jun 7 — Agents
- [ ] Planner, Nurturer, Sender as ADK agents + orchestrator (direct calls, no A2A)
- [ ] System prompts v1, iterated against the 3 scenarios
- [ ] **Pass gate (smoke test):** webhook → Planner → Nurturer → Sender → message in queue (full round-trip)

### Day 4 · Jun 8 — Dashboard
- [ ] Streamlit UI: ranked queue, EV rationale, reasoning trace, channel decision, send log
- [ ] Live updates (polling)
- [ ] **Pass gate:** queue + reasoning trace render as agents fire

### Day 5 · Jun 9 — Capture surface + scenario wiring
- [ ] Demo store page: signup form + chat widget → webhook → Planner trigger
- [ ] Wire + rehearse the 3 scenarios end to end
- [ ] **Pass gate:** real email lands in the test inbox; SMS/IG show as mock-labeled

### Day 6 · Jun 10 — Deploy + record
- [ ] Deploy backend + dashboard (Cloud Run); public URL
- [ ] Dress rehearsals; record + edit ≤ 3:00 video; English captions; upload to YouTube
- [ ] **Pass gate:** public dashboard URL returns 200; video uploaded

### Day 7 · Jun 11 AM — Submit (buffer)
- [ ] README + LICENSE (MIT) + architecture diagram
- [ ] Devpost writeup + links (repo + video + live URL)
- [ ] **Submit before 2:00 PM PT**

---

## 10. Pass criteria (definition of done)

- [ ] Atlas cluster online; connection returns OK
- [ ] Vector indexes created; aggregate query returns ≥1 result on each
- [ ] Planner webhook POST returns 200; ranked queue appears in dashboard
- [ ] Queue item shows drafted message + reasoning trace
- [ ] Real email lands in test inbox; SMS/IG queued with "would send" label
- [ ] Logs show inter-agent calls (Planner→Nurturer→Sender)
- [ ] Live dashboard public URL returns 200
- [ ] Demo video public on YouTube, ≤ 3:00, English captions
- [ ] Repo public, LICENSE present, README has setup steps
- [ ] Devpost submission accepted before Jun 11, 2:00 PM PT

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Python 3.14** — google-adk may lack wheels / support | Verify import Day 2 first thing. Fallback: pin to a 3.12 venv if ADK won't install |
| **A2A protocol** — new, under-documented | Already dropped — use direct ADK calls. Stretch only |
| **Meta IG approval** — 1–2 week delay | Mocked in UI, not on critical path |
| **Twilio toll-free verification** | SMS mocked; real send only to a verified test number if attempted |
| **Gemini rate limits during recording** | Throttle to sequential agent runs; cache responses |
| **Atlas free-tier 512 MB** | Keep data small (~18 customers / 50 products / 200 events) |
| **Vertex paid calls** | Embeddings are ~free (<1¢ for the whole dataset); confirm before any large reruns |

---

## 12. How to run (commands fill in as built)

```bash
# all commands from d:\hackathon, using the venv python
venv/Scripts/python.exe db/mongo.py            # 1. test Atlas connection
venv/Scripts/python.exe data/seed_data.py      # 2. load synthetic store
venv/Scripts/python.exe data/build_index.py    # 3. embed + create vector indexes (Day 1 pass gate)
# (Day 3+) run orchestrator / server / streamlit dashboard — TBD
```

---

## 13. Environment variables (`.env` — already set)

`PROJECT_ID`, `LOCATION` (Vertex AI) · `MONGODB_URI` (Atlas) · `SENDGRID_API_KEY` (email) ·
`TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` (SMS — mocked) · `META_ACCESS_TOKEN`,
`META_PAGE_ID` (IG — mocked). Google auth via local ADC (`application_default_credentials.json`).

---

## 14. Progress log

- **2026-06-03** — Vertex `text-embedding-004` embedding function working locally
  (`embeddings.py`, returns 768-dim vector). ✅
- **2026-06-04** — Plan locked (safe-ship tier + EV ranking). This document created.
  Day 1 data-layer build next.
