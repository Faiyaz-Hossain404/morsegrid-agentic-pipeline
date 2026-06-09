"""
Morsegrid Outfitters — Re-engagement Pipeline

Three-phase pipeline: Planner -> Nurturer -> Sender.
Agents access MongoDB exclusively through the MongoDB MCP server (hackathon requirement).
EV scoring is computed deterministically in the orchestrator (not by the LLM) to avoid
burning Gemini RPM quota on 18 back-to-back function-call round-trips.

Run:
    venv/Scripts/python.exe run_pipeline.py
"""
import os
import sys
import asyncio
import json
import re
import shutil
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
if os.getenv("PROJECT_ID"):
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID"))
if os.getenv("LOCATION"):
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("LOCATION"))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from tools.lead_scorer import score_lead_ev
from tools.product_search import find_similar_products
from tools.channel import pick_channel
from tools.email_sender import send_email_resend
from tools.mock_channels import send_sms_mock, send_ig_dm_mock
from db.mongo import get_db_client

DB_NAME = "morsegrid_outfitters"
PLANNER_MODEL  = os.getenv("PLANNER_MODEL",  "gemini-2.5-flash")
NURTURER_MODEL = os.getenv("NURTURER_MODEL", "gemini-2.5-flash")
SENDER_MODEL   = os.getenv("SENDER_MODEL",   "gemini-2.5-flash")
APP  = "morsegrid_pipeline"
USER = "pipeline_runner"
NPX  = shutil.which("npx") or ("npx.cmd" if sys.platform == "win32" else "npx")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_toolset() -> McpToolset:
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI missing from .env")
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=NPX,
                args=["-y", "mongodb-mcp-server"],
                env={**os.environ, "MDB_MCP_CONNECTION_STRING": uri},
            ),
            timeout=120,
        ),
    )


async def run_turn(runner: InMemoryRunner, session_id: str, text: str,
                   max_retries: int = 3):
    """Run one agent turn with automatic retry on 429 / RESOURCE_EXHAUSTED."""
    for attempt in range(max_retries):
        try:
            return await _run_turn_once(runner, session_id, text)
        except Exception as exc:
            err = str(exc)
            if ("429" in err or "RESOURCE_EXHAUSTED" in err) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"  [Rate limit] Waiting {wait}s before retry {attempt + 1}/{max_retries - 1}...")
                await asyncio.sleep(wait)
            else:
                raise


async def _run_turn_once(runner: InMemoryRunner, session_id: str, text: str):
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    tool_calls, final_parts = [], []

    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=msg):
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc:
                tool_calls.append(fc.name)
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                first3 = list(args.items())[:3]
                print(f"      [tool] {fc.name}({', '.join(f'{k}={v!r}' for k, v in first3)})")
            txt = getattr(part, "text", None)
            if txt and event.is_final_response():
                final_parts.append(txt)

    return "".join(final_parts), tool_calls


def extract_json(text: str):
    """Pull the first JSON object or array from an LLM response."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"([\[\{].*[\]\}])", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON found in agent output:\n{text[:400]}")


def score_all_customers(customers: list) -> list:
    """
    Compute EV scores for every customer in pure Python — no LLM round-trips.
    Returns the list sorted by score descending.
    """
    now = datetime.now(timezone.utc)
    scored = []
    for c in customers:
        raw_ts = c.get("last_active_at", "")
        try:
            if isinstance(raw_ts, datetime):
                # pymongo returns naive UTC datetimes — make them aware
                last_active = raw_ts.replace(tzinfo=timezone.utc) if raw_ts.tzinfo is None else raw_ts
            elif isinstance(raw_ts, (int, float)):
                last_active = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
            else:
                ts_str = str(raw_ts).replace("Z", "+00:00")
                last_active = datetime.fromisoformat(ts_str)
        except Exception:
            last_active = now

        days_inactive = max((now - last_active).days, 0)
        total_orders  = int(c.get("total_orders", 0))
        total_spend   = float(c.get("total_spend", 0.0))
        avg_order_val = (total_spend / total_orders) if total_orders > 0 else 250.0

        eng  = c.get("engagement") or {}
        last5 = eng.get("last5_opens") or []
        email_opens = sum(1 for v in last5 if v)
        sms_optin   = bool(eng.get("sms_optin", False))

        ev = score_lead_ev(
            customer_id=c["customer_id"],
            segment=c.get("segment", "cold"),
            days_inactive=days_inactive,
            total_orders=total_orders,
            avg_order_value=avg_order_val,
            email_opens_last_30d=email_opens,
            sms_opted_in=sms_optin,
        )

        scored.append({
            **c,
            "score":              ev["score"],
            "rationale":          ev["rationale"],
            "p_convert":          ev["p_convert"],
            "days_inactive":      days_inactive,
            "email_opens_last_30d": email_opens,
            "sms_opted_in":       sms_optin,
        })

    return sorted(scored, key=lambda x: x["score"], reverse=True)


async def make_runner(agent: LlmAgent, session_id: str) -> InMemoryRunner:
    runner = InMemoryRunner(agent=agent, app_name=APP)
    await runner.session_service.create_session(app_name=APP, user_id=USER, session_id=session_id)
    return runner


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run_pipeline():
    print()
    print("=" * 65)
    print("  MORSEGRID OUTFITTERS — RE-ENGAGEMENT PIPELINE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 65)
    print()

    toolset = build_toolset()

    try:
        # -------------------------------------------------------------------
        # PHASE 1 — PLANNER (pure Python — no LLM needed for a DB read + math)
        # Fetching data and scoring deterministically keeps all Gemini quota for
        # the Nurturer and Sender, which actually need language generation.
        # The Nurturer and Sender agents still use MongoDB exclusively via MCP.
        # -------------------------------------------------------------------
        print("[ 1 / 3 ]  PLANNER — Scoring re-engagement opportunities...")
        print()

        mongo_client = get_db_client()
        raw_customers = list(mongo_client[DB_NAME].customers.find({}))
        ranked = score_all_customers(raw_customers)
        leads  = ranked[:5]

        print(f"  -> Fetched {len(raw_customers)} customers from MongoDB.")
        print(f"  -> Scored with EV formula (P_convert x margin x recency). Top {len(leads)} leads:")
        for i, lead in enumerate(leads, 1):
            print(f"     {i}. {lead['name']:<22} segment={lead['segment']:<16} EV={lead['score']}")
        print()

        # -------------------------------------------------------------------
        # PHASE 2 — NURTURER (top 3 leads)
        # -------------------------------------------------------------------
        print("[ 2 / 3 ]  NURTURER AGENT")
        print("  Personalizing messages from behavior history + vector product search...")
        print()

        nurturer = LlmAgent(
            name="nurturer",
            model=NURTURER_MODEL,
            instruction=f"""You are the Nurturer for Morsegrid Outfitters' re-engagement pipeline.

For the customer you are given:
1. Call MongoDB find (database='{DB_NAME}', collection='behavior_events') filtered by
   customer_id, limit 15, to see their searches, views, and order history.
2. Call find_similar_products with a query that reflects their specific interests —
   use their search queries, viewed product tags, and behavior_summary.
3. Draft a warm, personal re-engagement email:
   - Sound like a real person at the store, NOT a marketing blast.
   - Reference the specific reason we are reaching out (back in stock, new arrival, etc.).
   - Name 1-2 recommended products with approximate prices.
   - Keep body under 200 words.
4. Return ONLY a valid JSON object:
   {{ "subject": "...", "body": "...", "recommended_product_ids": ["P001", ...] }}

Output ONLY the JSON object. No surrounding text.""",
            tools=[toolset, find_similar_products],
        )

        for idx, lead in enumerate(leads[:3]):
            cid = lead["customer_id"]
            print(f"  [{idx + 1}/3] Nurturing {lead['name']} ({cid}) — segment: {lead['segment']}")

            nurturer_sid = f"nurturer-{cid}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
            nurturer_runner = await make_runner(nurturer, nurturer_sid)

            prompt = (
                f"Customer ID: {cid} | Name: {lead['name']} | Segment: {lead['segment']} | "
                f"Score rationale: {lead['rationale']} | Days inactive: {lead['days_inactive']}. "
                f"Behavior summary: {lead.get('behavior_summary', 'N/A')}. "
                f"Fetch their events, find matching products, and draft the re-engagement message."
            )
            draft_out, nurturer_tools = await run_turn(nurturer_runner, nurturer_sid, prompt)
            draft = extract_json(draft_out)
            lead["draft"] = draft

            print(f"    -> Subject: {draft.get('subject', '(missing)')}")
            print(f"    -> Products: {draft.get('recommended_product_ids', [])}")
            print(f"    -> MCP calls: {', '.join(nurturer_tools)}")

            # Pause between Nurturer turns — flash has higher RPM but still needs breathing room
            if idx < 2:
                await asyncio.sleep(15)

        print()

        # -------------------------------------------------------------------
        # PHASE 3 — SENDER
        # -------------------------------------------------------------------
        print("[ 3 / 3 ]  SENDER AGENT")
        print("  Selecting channels, sending messages, logging to MongoDB...")
        print()

        sender = LlmAgent(
            name="sender",
            model=SENDER_MODEL,
            instruction=f"""You are the Sender for Morsegrid Outfitters' re-engagement pipeline.

For each customer you receive:
1. Call pick_channel(segment, email_opens_last_30d, sms_opted_in) to choose the channel.
2. Send via the matching tool:
   - "email"  -> send_email_resend(to_email, subject, body, customer_id)
   - "sms"    -> send_sms_mock(to_phone, body, customer_id)
   - "ig_dm"  -> send_ig_dm_mock(ig_handle, body, customer_id)
3. Call MongoDB insert-many (database='{DB_NAME}', collection='messages_sent') to log it.
   Document fields: customer_id, name, channel, subject, sent_at (ISO 8601 UTC now), status.
4. Reply: "Sent to [Name] via [channel] — [status]."

Complete all 4 steps. Do not skip the MongoDB log step.""",
            tools=[toolset, pick_channel, send_email_resend, send_sms_mock, send_ig_dm_mock],
        )

        results = []
        for idx, lead in enumerate(leads[:3]):
            if "draft" not in lead:
                print(f"  SKIP {lead['name']} — no draft generated.")
                continue

            cid   = lead["customer_id"]
            draft = lead["draft"]
            print(f"  [{idx + 1}/3] Sending to {lead['name']} ({cid})...")

            sender_sid = f"sender-{cid}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
            sender_runner = await make_runner(sender, sender_sid)

            prompt = (
                f"Customer ID: {cid} | Name: {lead['name']} | "
                f"Email: {lead['email']} | Phone: {lead.get('phone', 'N/A')} | "
                f"IG handle: {lead.get('ig_handle', 'N/A')} | "
                f"Segment: {lead['segment']} | "
                f"SMS opted in: {lead.get('sms_opted_in', False)} | "
                f"Email opens last 30d: {lead.get('email_opens_last_30d', 0)}. "
                f"Subject: {draft.get('subject', '')} | "
                f"Body: {draft.get('body', '')} "
                f"Send this message and log it to MongoDB now."
            )

            sender_out, sender_tools = await run_turn(sender_runner, sender_sid, prompt)
            results.append({"customer": lead["name"], "result": sender_out, "tools": sender_tools})

            print(f"    -> {sender_out.strip()[:120]}")
            print(f"    -> MCP calls: {', '.join(sender_tools)}")

            if idx < 2:
                await asyncio.sleep(15)

        # -------------------------------------------------------------------
        # SUMMARY
        # -------------------------------------------------------------------
        print()
        print("=" * 65)
        print("  PIPELINE COMPLETE")
        print("=" * 65)
        print(f"  Customers analyzed : {len(raw_customers)}")
        print(f"  Messages delivered : {len(results)}")
        print(f"  Demo inbox         : {os.getenv('DEMO_TO_EMAIL', 'N/A')}")
        print(f"  MongoDB collection : {DB_NAME}.messages_sent")
        print()
        print("  Check your inbox — emails should arrive within 30 seconds.")
        print("  MongoDB Atlas > messages_sent has the full delivery log.")
        print()

    finally:
        await toolset.close()


if __name__ == "__main__":
    asyncio.run(run_pipeline())
