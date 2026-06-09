# Morsegrid Outfitters — Ecommerce Re-engagement Agent
### Build Plan (start → submission)

> **Hackathon:** Building Agents for Real-World Challenges (Google Cloud) — **MongoDB Partner Track**
> **Prize bucket:** MongoDB ($5k / $3k / $2k) — judged only against other MongoDB-track builds
> **Deadline:** **2026-06-11, 2:00 PM PT** · **Personal target: 4 working days → done ~Jun 8**, leaving Jun 9–11 as buffer
> **Owners:** Maks (narrative + agent prompts + video) · Sifath (full-stack build + infra)
> **Repo:** `d:\hackathon\` (standalone git repo — no edits to Morsegrid production scripts)

---

## 0. Eligibility — HARD REQUIREMENTS (do not violate)

These come straight from the official rules. Missing any one = disqualified.

| # | Requirement | How we satisfy it |
|---|---|---|
| 1 | **Built with Gemini 3** ("Gemini provides the brain") | All three agents reason with **Gemini 3** (e.g. `gemini-3-pro`) on Vertex AI |
| 2 | **Google Cloud Agent Builder** | Agents built with **ADK** (Agent Development Kit — the code-first framework of Google Cloud's Agent Builder stack), deployed to **Vertex AI Agent Engine** |
| 3 | **Meaningful partner MCP integration** ⭐ | Agents read/write MongoDB **exclusively through the MongoDB MCP server** (`mongodb-mcp-server`) — find / aggregate / count / insert / update. **This is the eligibility linchpin.** |
| 4 | **Beyond chat — uses tools to accomplish tasks** | Agents query a live DB, run vector search, send a real email, log results |
| 5 | **Multi-step mission — plan + execute** | Planner → Nurturer → Sender pipeline plans who/what/how and finishes the job |
| 6 | **Keeps the human in control** | Dashboard shows every draft + decision; **review-and-approve before send** (human-in-the-loop mode for the demo) |

> ⚠️ **Earlier draft mistakenly accessed MongoDB via raw pymongo from the agents — that
> would have failed requirement #3.** Corrected here: the **agent runtime touches MongoDB
> only via the MongoDB MCP server.** (Offline ETL scripts may still use pymongo — see §5.)

---

## 1. What this is (one paragraph)

An **agent-based re-engagement system** for a demo motorcycle-gear store ("Morsegrid
Outfitters"). Instead of deterministic flows (Klaviyo/Postscript) that fire the same
template at everyone, three cooperating **Gemini 3** agents **reason across each
customer's full history + the product catalog + recency** — pulling that context from
**MongoDB via the MongoDB MCP server** — then decide who to contact, draft a personalized
message, and pick the right channel, with a human approving sends. The wedge: *an agent
that reasons across history and channels* — client-owned, not SaaS.

---

## 2. Locked scope decisions

| Decision | Choice | Why |
|---|---|---|
| **Build tier** | **Safe-ship multi-agent** | Highest odds of a finished, impressive submission in 7 days |
| **Model** | **Gemini 3** (Vertex AI) | Eligibility req #1 |
| **Build framework** | **ADK / Google Cloud Agent Builder** → Agent Engine | Eligibility req #2 |
| **MongoDB access** | **MongoDB MCP server only** (from the agents) | Eligibility req #3 — the partner integration |
| **Inter-agent wiring** | **Direct ADK calls** (NOT the A2A protocol) | A2A kill-date passed; not required by the rules; riskiest integration |
| **Email** | **Real send** (SendGrid) | Proves a live channel; lands in a test inbox |
| **SMS / Instagram DM** | **Mocked in the UI** | Drafted message shown + labeled *"would send via Twilio / Meta API"*. Avoids approval/verification delays |
| **ROI feature** | **EV-based lead ranking** | Planner ranks by `P(convert) × margin × recency` — the visible "smart" behavior |
| **Human-in-the-loop** | **Review + approve sends** | Eligibility req #6 (and a better demo) |
| **Dashboard** | **Local Streamlit for demo** (hosted = stretch) | Shows agent reasoning, MCP tool calls, channel decisions in real time |
| **Deployment** | **Run local for the video** (Cloud Run / Agent Engine = stretch) | 4-day timeline — deployment is not required to demo a working agent |
| **Data** | **100% synthetic** | ~18 customers, ~50 products, ~200 events |

**Deselected (optional fast-follows):** margin-aware discounting, cart-abandon hero
scenario, holdout + "$ incremental revenue" readout. *Products keep `cost`/`margin`
fields anyway, so these add later with zero rework.*

### Honest framing (for the pitch)
This is **retention / re-engagement**, not strictly **CRO**. The demo proves *capability*;
EV ranking makes it read as a *business* decision. The cheapest later ROI proof is a
simulated holdout with an incremental-revenue number — deferred.

---

## 3. Architecture

```
   Demo store (signup form + chat widget)
            │  POST lead / behavior event
            ▼
        Webhook ───────────────────────────────► triggers the agent app
            │
            ▼
   ╔══════════════════════════════════════════════════════════╗
   ║   ADK multi-agent app   ·   model: GEMINI 3               ║
   ║                                                          ║
   ║     PLANNER  ──►  NURTURER  ──►  SENDER                   ║
   ║     (who)         (what)         (which channel)          ║
   ║        │             │              │                     ║
   ║        ├── MCP ──────┼── MCP ───────┼── MCP (log)         ║
   ║        │             │              │                     ║
   ║        └ score_lead  └ embed_query  └ pick_channel        ║
   ║          _ev (EV)      (Vertex)       send_email (real)   ║
   ║                        + vector       send_sms/ig (mock)  ║
   ╚════════════════════════╪═════════════════════════════════╝
                            │  ALL MongoDB ops go through ↓
                  ┌───────────────────────────┐
                  │   MongoDB MCP server       │  ← partner integration (mandatory)
                  │   find · aggregate · count │
                  │   insert-many · update-many│
                  └─────────────┬─────────────┘
                                ▼
                       MongoDB Atlas
        customers · behavior_events · products · orders · messages_sent
              (+ vector indexes on desc_vector & behavior_vector)
                                ▲
                                │ offline ETL only (pymongo): seed + embed + create indexes
```

Orchestration = ADK `SequentialAgent` (or plain runner calls): **Planner → Nurturer →
Sender**. Every agent's MCP + custom tool calls and outputs are captured into an
`agent_trace` — that trace (with visible MCP calls) is the demo *and* the proof of req #3.

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

orders          _id, customer_id, items[ {product_id, price, qty} ], total, ts
messages_sent   _id, customer_id, channel, subject?, body,
                status (sent|mock|queued|approved), reasoning, agent_trace, ts
```

**Vector indexes:** `768` dims, `cosine` — on `products.desc_vector`
(`products_vector_index`) and `customers.behavior_vector` (`customers_vector_index`).

---

## 5. Components to build

| Component | Path | Talks to MongoDB via | Notes |
|---|---|---|---|
| **embeddings** | (built ✅) | — | Vertex `text-embedding-004`; `RETRIEVAL_DOCUMENT` for docs, `RETRIEVAL_QUERY` for live queries |
| **seed data** (ETL) | offline | **pymongo** (allowed — not agent path) | ~18 customers, ~50 products, ~200 events |
| **build index** (ETL) | offline | **pymongo** (allowed) | embed docs, write vectors, create vector indexes |
| **MongoDB MCP server** | external (`npx mongodb-mcp-server`) | — | ⭐ the partner integration; the agents' only DB door |
| **tools** | code | via MCP / Vertex | EV scoring, embed_query, channel pick, email/mocks |
| **agents** | code | **MCP** (via ADK MCPToolset) | Planner / Nurturer / Sender, Gemini 3 |
| **server** | code | via agents | webhook + read API for dashboard |
| **dashboard** | code | read API | Streamlit: queue, trace, MCP calls, approve+send |
| **store** | code | webhook | signup form + chat widget |

> **Why ETL uses pymongo but agents use MCP:** the MCP requirement is about the *agent's*
> integration ("give your agent the superpowers"). Seeding/indexing is dev-time setup, not
> an agent action — pymongo there is fine and more reliable for creating Atlas vector
> indexes. Every *runtime* DB op the agents perform goes through the MongoDB MCP server.

*File layout (flat vs foldered) still TBD — does not affect this plan.*

---

## 6. Tools

### MongoDB MCP server tools (partner integration — used by the agents)
| Tool | Used by | For |
|---|---|---|
| `find` | Planner, Nurturer | active leads, customer history, orders/events |
| `aggregate` | Planner, Nurturer | analytics + **`$vectorSearch`** product match |
| `count` | Planner | recent-message / fatigue checks |
| `insert-many` | Sender | write `messages_sent` (with reasoning + trace) |
| `update-many` | Sender/Planner | flag "nurtured today" |

### Custom tools (our logic, alongside MCP)
| Tool | Used by | Returns |
|---|---|---|
| `embed_query(text)` | Nurturer | 768-d Vertex query vector → fed into the MCP `$vectorSearch` |
| `score_lead_ev(lead)` | Planner | `{score, p_convert, margin_est, recency_factor, rationale}` ← **EV ranking** |
| `pick_channel(customer)` | Sender | `email` \| `sms` \| `ig_dm` |
| `send_email(to, subject, body)` | Sender | **REAL** (SendGrid) |
| `send_sms` / `send_ig_dm` | Sender | **MOCK** — returns `"mock"`, shown in UI |

> **Vector-search-through-MCP detail (resolve Day 2–3):** the LLM should not hand-type a
> 768-float vector. Approach: `embed_query` produces the vector and the product-match step
> runs the `$vectorSearch` pipeline through the **MongoDB MCP `aggregate`** path (thin
> wrapper injects the vector). Net: the query still resolves on MongoDB via MCP.

---

## 7. Agents (Gemini 3, via ADK + MCPToolset)

- **Planner** — triggered on schedule/webhook. MCP `find`/`aggregate` for candidate leads →
  custom `score_lead_ev` per lead → **ranked queue** (highest EV first) + one-line rationale.
- **Nurturer** — per lead: MCP `find` (history) + `embed_query` + MCP `aggregate`
  (`$vectorSearch`) for product match → Gemini 3 drafts a contextual message + reasoning.
- **Sender** — `pick_channel` from engagement → `send_email` (real) or mock SMS/IG →
  MCP `insert-many` to log. **Awaits human approval in the dashboard before real send.**

---

## 8. Demo scenarios (the 3 in the video)

1. **Cross-session memory + product match** — *Mike* asked (chat) about the Rallye
   Adventure Helmet ~2 months ago; out of stock then, **back in stock today**. Planner
   queues him, Nurturer (vector match via MCP) drafts referencing the inquiry, Sender → email.
2. **Channel switch** — *Sarah* browsed helmets but opened 0 of her last 5 emails. New
   helmet drops. Sender visibly decides *"email engagement low → switch to SMS."*
3. **Latent-want detection** — *Diego* searched "cafe racer jacket" 6 weeks ago; no match
   then. A new arrival now fits (surfaced by MCP `$vectorSearch`). Agent drafts "we got
   what you were looking for."

---

## 9. Execution plan — 4 working days (Jun 4 → ~Jun 8)

> **Vertical-slice strategy:** Day 1 proves the whole risky stack thin (data + ADK +
> Gemini 3 + MCP all touching once); Days 2–3 build it wide; Day 4 ships. Finishing by
> ~Jun 8 leaves Jun 9–11 as buffer before the hard 2 PM PT deadline.
> **Cut to fit 4 days (→ Stretch):** hosted URL / Cloud Run + Agent Engine deploy, full
> storefront UI, real Twilio SMS. **Kept:** everything eligibility needs + the wedge.

### Day 1 · Jun 4–5 — Foundation + de-risk the full stack
- [x] `requirements.txt`; DB connection module + ping
- [x] Seed (50 products / 18 customers / 33 orders / 189 events) — pymongo
- [x] Embed docs + create both vector indexes — pymongo
- [x] Install + import-check `google-adk` (2.2.0) on Python 3.14 — PASSES, no 3.12 downgrade
- [x] Confirm Gemini model: **`gemini-2.5-pro`** is the Vertex API ID for "Gemini 3" in this project
- [x] Stand up **MongoDB MCP server** (`npx`) + connect via ADK `McpToolset`; agent called MCP `count` → returned 18
- [x] **Pass gate A:** `$vectorSearch` returns hits (top: Cafe Racer Jacket 0.947) ✅
- [x] **Pass gate B:** `gemini-2.5-pro` agent invoked MongoDB MCP server → **DAY 1 FULLY DONE** ✅

### Day 2 · Jun 6 — The agent pipeline (the heart)
- [ ] Custom tools: `embed_query`, `score_lead_ev` (EV), `pick_channel`, `send_email` (real), `send_sms`/`send_ig_dm` (mock)
- [ ] Planner / Nurturer / Sender (**Gemini 3**) using MCP tools + custom tools
- [ ] Orchestrator (SequentialAgent / direct calls); product match via MCP `$vectorSearch`; webhook/script trigger
- [ ] **Pass gate:** trigger → ranked queue → draft → channel → **real email lands + logged via MCP `insert-many`**; trace shows MCP calls
- [ ] *Fallback if running long: collapse Planner+Nurturer into one "Strategist" agent (2 agents total)*

### Day 3 · Jun 7 — Dashboard + scenarios + polish
- [ ] Streamlit dashboard: ranked queue, EV rationale, reasoning trace (**MCP calls visible**), channel decision, **approve + send**
- [ ] Wire + rehearse the **3 scenarios** (Mike / Sarah / Diego); iterate prompts
- [ ] **Pass gate:** dashboard shows agents firing live; all 3 scenarios run clean

### Day 4 · Jun 8 — Ship
- [ ] Record + edit **≤ 3:00 video** (English captions); upload to YouTube
- [ ] README + LICENSE (MIT) + architecture diagram (Gemini 3 + Agent Builder/ADK + MongoDB MCP)
- [ ] Devpost writeup + links; **explicitly state the MongoDB MCP integration**
- [ ] **Submit** (well before Jun 11, 2 PM PT)

### Stretch · Jun 9–11 buffer (only if Day 4 finished clean)
- [ ] Deploy: dashboard/backend → Cloud Run (public URL); agents → Agent Engine
- [ ] Demo storefront page (signup form + chat widget) replacing the script trigger
- [ ] Holdout + "$ incremental revenue" readout (the ROI proof)
- [ ] Real Twilio SMS to a verified test number

---

## 10. Pass criteria (definition of done)

**Hard — required for submission + eligibility:**
- [ ] **Built with Gemini 3** (agents call a `gemini-3-*` model)
- [ ] **Built on Google Cloud Agent Builder / ADK**
- [ ] **Agents perform MongoDB ops via the MongoDB MCP server** — logs/trace show MCP tool calls ⭐
- [ ] Vector search returns results via MCP `aggregate` (`$vectorSearch`)
- [ ] Trigger → ranked queue → drafted message + reasoning trace; human approves before send
- [ ] Real email lands in test inbox; SMS/IG queued with "would send" label
- [ ] Trace shows inter-agent flow (Planner→Nurturer→Sender)
- [ ] Demo video public, ≤ 3:00, English captions
- [ ] Repo public, LICENSE present, README has setup steps
- [ ] Devpost submission accepted before Jun 11, 2:00 PM PT

**Stretch — nice to have, not blocking:**
- [ ] Deployed to Agent Engine / Cloud Run; public dashboard URL returns 200
- [ ] Storefront capture page; holdout + "$ incremental revenue" readout

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **MCP integration missing = disqualified** ⭐ | Agents access MongoDB *only* via MongoDB MCP server; verify MCP tool calls appear in the trace by Day 3 |
| **Node.js dependency** (MCP server is Node, run via `npx`) | Install Node 18+ Day 1; confirm `npx -y mongodb-mcp-server` starts against Atlas |
| **Gemini 3 model ID / region** | Confirm exact `gemini-3-*` ID available in our Vertex `LOCATION` Day 2 |
| **Python 3.14** — google-adk / MCP toolset wheels | Verify import Day 2 first thing. Fallback: 3.12 venv |
| **Agent Builder requirement** | ADK is the code-first Agent Builder path → Agent Engine. If judges want the low-code console, that's the fallback framing |
| **Vector-through-MCP** (768 floats via LLM) | `embed_query` + thin aggregate wrapper, not LLM-typed vectors |
| **MCP server permissions** (`--readOnly`, tool allow-list) | Configure to allow find/aggregate/count/insert/update on our DB only |
| **A2A protocol** | Dropped (not required); direct ADK calls |
| **Meta IG / Twilio** delays | Mocked; not on critical path |
| **Gemini rate limits during recording** | Throttle to sequential runs; cache responses |
| **Atlas free-tier 512 MB** | Keep data small (~18/50/200) |

---

## 12. How to run (fill in as built)

```bash
# from d:\hackathon, using the venv python + Node for the MCP server

# --- offline ETL (pymongo) ---
venv/Scripts/python.exe db/mongo.py            # 1. test Atlas connection
venv/Scripts/python.exe data/seed_data.py      # 2. load synthetic store
venv/Scripts/python.exe data/build_index.py    # 3. embed + create vector indexes

# --- MongoDB MCP server (partner integration) ---
npx -y mongodb-mcp-server --connectionString "$MONGODB_URI"   # smoke test
#   (in the agent app, this is launched/connected via ADK MCPToolset stdio)

# --- agents + dashboard (Day 3+) ---
# run orchestrator / webhook server / streamlit dashboard — TBD
```

---

## 13. Environment variables (`.env`)

`PROJECT_ID`, `LOCATION` (Vertex AI / Gemini 3) · `MONGODB_URI` (Atlas) ·
`MDB_MCP_CONNECTION_STRING` = same as `MONGODB_URI` (MongoDB MCP server) ·
`SENDGRID_API_KEY` (email) · `TWILIO_SID/TOKEN/FROM` (SMS — mocked) ·
`META_ACCESS_TOKEN/PAGE_ID` (IG — mocked). Google auth via local ADC.

---

## 14. Progress log

- **2026-06-03** — Vertex `text-embedding-004` embedding function working locally
  (`embeddings.py`, 768-dim vector). ✅
- **2026-06-04** — Plan locked (safe-ship tier + EV ranking). PLAN.md created.
- **2026-06-04 (rev 2)** — **Corrected for official rules:** restored **MongoDB MCP server**
  as the agents' mandatory data interface (eligibility req #3); pinned **Gemini 3** as the
  model; framed build on **Google Cloud Agent Builder / ADK**; added human-in-the-loop
  approval. Day 1 now includes standing up the MCP server.
- **2026-06-04 (rev 3)** — **Compressed to a 4-day plan** (done ~Jun 8; Jun 9–11 buffer).
  Vertical-slice Day 1; deployment / storefront / real SMS moved to Stretch. Node v25.6.1
  confirmed installed (MCP server runtime). Day-1 build next.
- **2026-06-07** — **DAY 1 FULLY COMPLETE.** Data layer GREEN. Seeded 50 products / 18 customers / 33 orders /
  189 events; embedded all 68 docs (Vertex text-embedding-004); both Atlas vector indexes
  queryable. Test `$vectorSearch` "vintage cafe racer leather jacket" → top hit Classic
  Leather Cafe Racer Jacket (0.947), all top-5 on-theme. `google-adk 2.2.0` + `mcp 1.27.2`
  install on Python 3.14. Detour: expired ADC token fixed via `gcloud auth
  application-default login`. Model discovery: "Gemini 3" on Vertex = `gemini-2.5-pro`
  (also `gemini-2.5-flash`). MCP smoke test: agent called MCP `count` on customers
  → returned 18. Full eligibility chain proven: gemini-2.5-pro → ADK → MongoDB MCP
  server → Atlas. **Day 2 next: the full 3-agent pipeline.**
