"""
Morsegrid Outfitters — AI Revenue Recovery Pipeline (headless).

Planner -> Nurturer -> Sender across BOTH opportunity types:
  * abandoned carts (time-sensitive)   * dormant customers (re-engagement)

The Planner scores deterministically (no LLM) so Gemini quota is spent on language
generation, not ranking. The Nurturer and Sender agents access MongoDB exclusively
through the MongoDB MCP server (hackathon eligibility requirement); the Sender even
writes its delivery log back via the MCP insert-many tool.

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
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GEMINI_LOCATION", "global")

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from planner import build_opportunity_queue
from nurturer_prompts import NURTURER_INSTRUCTION, build_prompt
from tools.product_search import find_similar_products
from tools.channel import pick_channel
from tools.email_sender import send_email_resend
from tools.mock_channels import send_sms_mock, send_ig_dm_mock

DB_NAME        = "morsegrid_outfitters"
NURTURER_MODEL = os.getenv("NURTURER_MODEL", "gemini-3-flash-preview")
SENDER_MODEL   = os.getenv("SENDER_MODEL",   "gemini-3-flash-preview")
APP  = "morsegrid_pipeline"
USER = "pipeline_runner"
NPX  = shutil.which("npx") or ("npx.cmd" if sys.platform == "win32" else "npx")
TOP_N = int(os.getenv("PIPELINE_TOP_N", "3"))


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


async def run_turn(runner: InMemoryRunner, session_id: str, text: str, max_retries: int = 3):
    """Run one agent turn with automatic retry on 429 / RESOURCE_EXHAUSTED."""
    for attempt in range(max_retries):
        try:
            return await _run_turn_once(runner, session_id, text)
        except Exception as exc:
            err = str(exc)
            if ("429" in err or "RESOURCE_EXHAUSTED" in err) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"  [Rate limit] waiting {wait}s before retry...")
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
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"([\[\{].*[\]\}])", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON found in agent output:\n{text[:400]}")


async def make_runner(agent: LlmAgent, session_id: str) -> InMemoryRunner:
    runner = InMemoryRunner(agent=agent, app_name=APP)
    await runner.session_service.create_session(app_name=APP, user_id=USER, session_id=session_id)
    return runner


async def run_pipeline():
    print("\n" + "=" * 66)
    print("  MORSEGRID OUTFITTERS — AI REVENUE RECOVERY PIPELINE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 66 + "\n")

    toolset = build_toolset()
    try:
        # ---- PHASE 1 — PLANNER (deterministic ranking; no LLM) ----
        print("[ 1 / 3 ]  PLANNER — ranking abandoned carts + dormant customers...\n")
        queue = build_opportunity_queue(DB_NAME)
        leads = queue[:TOP_N]
        n_cart = sum(1 for o in queue if o["opp_type"] == "abandoned_cart")
        print(f"  -> {len(queue)} opportunities ({n_cart} carts, {len(queue) - n_cart} dormant). Top {len(leads)}:")
        for i, o in enumerate(leads, 1):
            tag = "CART " if o["opp_type"] == "abandoned_cart" else "DORM "
            extra = (f"${o.get('cart_value', 0):.0f} cart" if o["opp_type"] == "abandoned_cart"
                     else f"{o.get('days_inactive')}d dormant")
            print(f"     {i}. [{tag}] {o['name']:<18} EV=${o['score']:<7} ({extra})")
        print()

        # ---- PHASE 2 — NURTURER ----
        print("[ 2 / 3 ]  NURTURER AGENT — personalizing via MCP + Atlas Vector Search...\n")
        nurturer = LlmAgent(
            name="nurturer", model=NURTURER_MODEL,
            instruction=NURTURER_INSTRUCTION,
            tools=[toolset, find_similar_products],
        )
        for idx, lead in enumerate(leads):
            cid = lead["customer_id"]
            print(f"  [{idx + 1}/{len(leads)}] Nurturing {lead['name']} ({cid}) — {lead['opp_type']}")
            sid = f"nurturer-{cid}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
            runner = await make_runner(nurturer, sid)
            out, tools = await run_turn(runner, sid, build_prompt(lead))
            draft = extract_json(out)
            lead["draft"] = draft
            print(f"    -> Subject: {draft.get('subject', '(missing)')}")
            print(f"    -> Products: {draft.get('recommended_product_ids', [])}")
            print(f"    -> MCP/tool calls: {', '.join(tools)}")
            if idx < len(leads) - 1:
                await asyncio.sleep(15)
        print()

        # ---- PHASE 3 — SENDER ----
        print("[ 3 / 3 ]  SENDER AGENT — channel select, deliver, log to MongoDB via MCP...\n")
        sender = LlmAgent(
            name="sender", model=SENDER_MODEL,
            instruction=f"""You are the Sender for Morsegrid Outfitters' revenue-recovery pipeline.

For each shopper you receive:
1. Call pick_channel(segment, email_opens_last_30d, sms_opted_in) to choose the channel.
2. Send via the matching tool:
   - "email"  -> send_email_resend(to_email, subject, body, customer_id)
   - "sms"    -> send_sms_mock(to_phone, body, customer_id)
   - "ig_dm"  -> send_ig_dm_mock(ig_handle, body, customer_id)
3. Call MongoDB insert-many (database='{DB_NAME}', collection='messages_sent') to log it.
   Document fields: customer_id, name, opp_type, channel, subject, sent_at (ISO 8601 UTC now), status.
4. Reply: "Sent to [Name] via [channel] — [status]."

Complete all 4 steps. Do not skip the MongoDB log step.""",
            tools=[toolset, pick_channel, send_email_resend, send_sms_mock, send_ig_dm_mock],
        )
        results = []
        for idx, lead in enumerate(leads):
            if "draft" not in lead:
                print(f"  SKIP {lead['name']} — no draft.")
                continue
            cid, draft = lead["customer_id"], lead["draft"]
            print(f"  [{idx + 1}/{len(leads)}] Sending to {lead['name']} ({cid})...")
            sid = f"sender-{cid}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
            runner = await make_runner(sender, sid)
            prompt = (
                f"Customer ID: {cid} | Name: {lead['name']} | Opp type: {lead['opp_type']} | "
                f"Email: {lead['email']} | Phone: {lead.get('phone', 'N/A')} | "
                f"IG handle: {lead.get('ig_handle', 'N/A')} | Segment: {lead['segment']} | "
                f"SMS opted in: {lead.get('sms_opted_in', False)} | "
                f"Email opens last 30d: {lead.get('email_opens_last_30d', 0)}. "
                f"Subject: {draft.get('subject', '')} | Body: {draft.get('body', '')} "
                f"Send this message and log it to MongoDB now."
            )
            out, tools = await run_turn(runner, sid, prompt)
            results.append({"customer": lead["name"], "result": out, "tools": tools})
            print(f"    -> {out.strip()[:120]}")
            print(f"    -> MCP/tool calls: {', '.join(tools)}")
            if idx < len(leads) - 1:
                await asyncio.sleep(15)

        print("\n" + "=" * 66)
        print("  PIPELINE COMPLETE")
        print("=" * 66)
        print(f"  Opportunities analyzed : {len(queue)}")
        print(f"  Messages delivered     : {len(results)}")
        print(f"  Demo inbox             : {os.getenv('DEMO_TO_EMAIL', 'N/A')}")
        print(f"  MongoDB collection     : {DB_NAME}.messages_sent")
        print("\n  Check your inbox; the messages_sent collection has the delivery log.\n")
    finally:
        await toolset.close()


if __name__ == "__main__":
    asyncio.run(run_pipeline())
