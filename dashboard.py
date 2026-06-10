"""
Morsegrid Outfitters — AI Revenue Recovery Agent (dashboard)

One pipeline recovers two kinds of lost revenue:
  * Abandoned carts      — high-intent, time-sensitive
  * Dormant customers    — re-engagement / retention

Planner ranks every opportunity -> Nurturer (Gemini 3 + ADK + MongoDB MCP) drafts
a personalized message -> human approves -> Sender picks a channel, delivers, logs.
Agents access MongoDB exclusively through the MongoDB MCP server (eligibility req).

Run:
    venv/Scripts/streamlit.exe run dashboard.py
"""
import os
import sys
import asyncio
import json
import re
import shutil
import time
import threading
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
if os.getenv("PROJECT_ID"):
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID"))
# Gemini 3 Flash is served from the `global` endpoint (it 404s in us-central1).
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GEMINI_LOCATION", "global")

import streamlit as st

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from db.mongo import get_db_client
from planner import build_opportunity_queue
from nurturer_prompts import NURTURER_INSTRUCTION, build_prompt
from tools.product_search import find_similar_products
from tools.channel import pick_channel
from tools.email_sender import send_email_resend
from tools.mock_channels import send_sms_mock, send_ig_dm_mock
from ingest.shopify import simulate_incoming_cart

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_NAME        = "morsegrid_outfitters"
NURTURER_MODEL = os.getenv("NURTURER_MODEL", "gemini-3-flash-preview")
APP            = "morsegrid_dashboard"
USER_ID        = "dashboard_user"
NPX            = shutil.which("npx") or ("npx.cmd" if sys.platform == "win32" else "npx")

HERO_CART_IDS    = {"C001", "C002", "C003"}   # Mike / Sarah / Diego
HERO_DORMANT_IDS = {"C004", "C005"}           # Ava / Marcus
HERO_IDS         = HERO_CART_IDS | HERO_DORMANT_IDS

OPP_BADGE = {
    "abandoned_cart": ":material/shopping_cart_checkout: CART",
    "dormant":        ":material/bedtime: RE-ENGAGE",
}
SEGMENT_ICONS = {
    "VIP":            ":material/workspace_premium:",
    "dormant_vip":    ":material/workspace_premium:",
    "repeat":         ":material/repeat:",
    "engaged":        ":material/thumb_up:",
    "cart-abandoner": ":material/remove_shopping_cart:",
    "dormant_email":  ":material/mark_email_unread:",
    "one-time":       ":material/person:",
    "cold":           ":material/ac_unit:",
}
CHANNEL_LABELS = {
    "email": ":material/mail: EMAIL",
    "sms":   ":material/sms: SMS",
    "ig_dm": ":material/photo_camera: IG DM",
}

# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

def log_event(level: str, message: str):
    if "activity_log" not in st.session_state:
        st.session_state.activity_log = []
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    st.session_state.activity_log.append({"ts": ts, "level": level, "msg": message})


def render_activity_log():
    log = st.session_state.get("activity_log", [])
    if not log:
        st.caption("No activity yet.")
        return
    icon_map = {
        "success": ":material/check_circle:",
        "error":   ":material/cancel:",
        "info":    ":material/info:",
        "warning": ":material/warning:",
    }
    for entry in reversed(log[-25:]):
        icon = icon_map.get(entry["level"], ":material/radio_button_unchecked:")
        st.caption(f"`{entry['ts']}` {icon} {entry['msg']}")


# ---------------------------------------------------------------------------
# Async infra
# ---------------------------------------------------------------------------

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


async def agent_turn(runner: InMemoryRunner, session_id: str, text: str):
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    tool_trace, final_parts = [], []

    async for event in runner.run_async(user_id=USER_ID, session_id=session_id, new_message=msg):
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc:
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                tool_trace.append({
                    "tool": fc.name,
                    "args": {k: v for k, v in list(args.items())[:4]},
                    "is_mcp": fc.name in {
                        "find", "aggregate", "count", "insert-many",
                        "update-many", "delete-many", "list-collections",
                    },
                })
            txt = getattr(part, "text", None)
            if txt and event.is_final_response():
                final_parts.append(txt)

    return "".join(final_parts), tool_trace


def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"([\[\{].*[\]\}])", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON found in agent output:\n{text[:400]}")


# ---------------------------------------------------------------------------
# Planner — background task wrapper (cancellable)
# ---------------------------------------------------------------------------

class PlannerTask:
    def __init__(self):
        self.result:    list | None = None
        self.error:     str  | None = None
        self.done:      bool        = False
        self.cancelled: bool        = False


def _planner_worker(task: PlannerTask):
    try:
        result = build_opportunity_queue(DB_NAME)
        if not task.cancelled:
            task.result = result
    except Exception as exc:
        if not task.cancelled:
            task.error = str(exc)
    finally:
        task.done = True


# ---------------------------------------------------------------------------
# Nurturer — ADK agent + MCP (branches on opportunity type)
# ---------------------------------------------------------------------------

async def _nurturer_async(opp: dict):
    toolset = build_toolset()
    try:
        agent = LlmAgent(
            name="nurturer",
            model=NURTURER_MODEL,
            instruction=NURTURER_INSTRUCTION,
            tools=[toolset, find_similar_products],
        )
        sid = f"dash-nur-{opp['customer_id']}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        runner = InMemoryRunner(agent=agent, app_name=APP)
        await runner.session_service.create_session(app_name=APP, user_id=USER_ID, session_id=sid)

        prompt = build_prompt(opp)
        output, tool_trace = await agent_turn(runner, sid, prompt)
        draft = extract_json(output)
        body = draft.get("body", "")
        if "Morsegrid Outfitters Team" not in body:
            draft["body"] = body.rstrip() + "\n\nBest,\nThe Morsegrid Outfitters Team"
        return draft, tool_trace
    finally:
        await toolset.close()


def run_nurturer(opp: dict):
    return run_async(_nurturer_async(opp))


# ---------------------------------------------------------------------------
# Sender — deterministic (pick channel -> deliver -> log via Mongo)
# Sender picks the channel from engagement signals, so an email-dead shopper
# (Sarah) is automatically switched to SMS.
# ---------------------------------------------------------------------------

def _send_direct(opp: dict, draft: dict):
    decision = pick_channel(
        segment=opp.get("segment", "cold"),
        email_opens_last_30d=opp.get("email_opens_last_30d", 0),
        sms_opted_in=opp.get("sms_opted_in", False),
    )
    channel = decision["channel"]
    subject = draft.get("subject", "")
    body    = draft.get("body", "")
    cid     = opp["customer_id"]

    if channel == "email":
        send_result = send_email_resend(opp.get("email", ""), subject, body, cid)
    elif channel == "sms":
        send_result = send_sms_mock(opp.get("phone", ""), body, cid)
    else:
        send_result = send_ig_dm_mock(opp.get("ig_handle", ""), body, cid)

    status = send_result.get("status", "sent")
    if status not in ("sent", "mock_sent"):
        raise RuntimeError(f"Delivery failed: {send_result.get('error', 'unknown error')}")

    mongo_client = get_db_client()
    db = mongo_client[DB_NAME]
    db["messages_sent"].insert_one({
        "customer_id":  cid,
        "name":         opp["name"],
        "opp_type":     opp["opp_type"],
        "channel":      channel,
        "channel_reason": decision["reason"],
        "subject":      subject,
        "cart_id":      opp.get("cart_id"),
        "sent_at":      datetime.now(timezone.utc).isoformat(),
        "status":       status,
    })
    # Close the loop: mark the cart as having a recovery message out.
    if opp["opp_type"] == "abandoned_cart" and opp.get("cart_id"):
        db["abandoned_carts"].update_one(
            {"cart_id": opp["cart_id"]}, {"$set": {"recovery_status": "sent"}}
        )

    send_label = "mock-sent (would send via " + ("Twilio" if channel == "sms" else "Meta API") + ")" \
        if status == "mock_sent" else status
    tool_trace = [
        {"tool": "pick_channel", "args": {"channel": channel, "reason": decision["reason"][:48]}, "is_mcp": False},
        {"tool": f"send_{channel}", "args": {"to": opp.get("email" if channel == "email" else "phone", "")}, "is_mcp": False},
        {"tool": "mongodb.insert_one", "args": {"collection": "messages_sent", "status": status}, "is_mcp": False},
    ]
    return f"Sent to {opp['name']} via {channel} — {send_label}.", tool_trace, channel, decision["reason"]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def render_trace(tool_trace: list):
    if not tool_trace:
        st.caption("No tool calls recorded.")
        return
    for entry in tool_trace:
        args_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in entry.get("args", {}).items())
        if entry.get("is_mcp"):
            st.markdown(f":blue[**MCP**] &nbsp; `{entry['tool']}({args_str})`")
        else:
            st.markdown(f":green[**TOOL**] &nbsp; `{entry['tool']}({args_str})`")


def status_chip(cid: str) -> tuple:
    if cid in st.session_state.get("sent", {}):
        r = st.session_state.sent[cid].get("result", "")
        return (":material/cancel:", "REJECTED") if r == "rejected" \
            else (":material/check_circle:", "SENT")
    if cid in st.session_state.get("drafts", {}):
        return (":material/description:", "DRAFT READY")
    if cid in st.session_state.get("errors", {}):
        return (":material/error:", "ERROR")
    return (":material/radio_button_unchecked:", "PENDING")


def opp_detail(opp: dict) -> str:
    if opp["opp_type"] == "abandoned_cart":
        soldout = "" if opp.get("items_in_stock", True) else " · item sold out"
        return f"${opp.get('cart_value', 0):.0f} cart · {opp.get('hours_since_abandon')}h ago{soldout}"
    return f"dormant {opp.get('days_inactive', '?')}d · {opp.get('total_orders', 0)} orders"


def scoring_table_md(opps: list) -> str:
    rows = [
        "| # | Name | Type | Segment | EV $ | P | Detail | Status |",
        "|---|------|------|---------|------|---|--------|--------|",
    ]
    for i, o in enumerate(opps, 1):
        em, lbl = status_chip(o["customer_id"])
        typ = "🛒 Cart" if o["opp_type"] == "abandoned_cart" else "💤 Re-engage"
        rows.append(
            f"| {i} | {o['name']} | {typ} | {o['segment']} | **{o['score']}** | "
            f"{o['p_value']:.0%} | {opp_detail(o)} | {em} {lbl} |"
        )
    return "\n".join(rows)


def render_cart_card(opp: dict):
    """Show the abandoned cart contents — 'all the info about that abandoned session'."""
    stage_label = {
        "payment_info": ":material/credit_card: reached payment",
        "checkout_started": ":material/shopping_cart_checkout: started checkout",
        "cart": ":material/add_shopping_cart: added to cart",
    }.get(opp.get("cart_stage"), opp.get("cart_stage", ""))

    st.markdown(
        f":material/shopping_cart: **Abandoned cart `{opp.get('cart_id')}`** "
        f"· {stage_label} · abandoned **{opp.get('hours_since_abandon')}h** ago "
        f"· source `{opp.get('source', 'shopify')}`"
    )
    for it in opp.get("cart_items", []):
        stock = ":green[in stock]" if it.get("in_stock_now", True) else ":red[**SOLD OUT**]"
        st.markdown(f"- `{it.get('product_id')}` **{it.get('title')}** — ${it.get('price', 0):.0f} · {stock}")
    if opp.get("cart_note"):
        st.caption(f":material/sticky_note_2: {opp['cart_note']}")


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Morsegrid — AI Revenue Recovery",
        page_icon="🏍",
        layout="wide",
    )

    for key, default in [
        ("leads", []), ("drafts", {}), ("sent", {}),
        ("errors", {}), ("activity_log", []),
        ("is_planning", False), ("planner_task", None),
        ("force_expanded", set()),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # ---- Planner task completion check ----
    if st.session_state.is_planning:
        task: PlannerTask = st.session_state.planner_task
        if task and task.done:
            st.session_state.is_planning = False
            st.session_state.planner_task = None
            if task.result is not None:
                st.session_state.leads  = task.result
                st.session_state.drafts = {}
                st.session_state.sent   = {}
                st.session_state.errors = {}
                n_cart = sum(1 for o in task.result if o["opp_type"] == "abandoned_cart")
                log_event("success", f"Planner ranked {len(task.result)} opportunities ({n_cart} carts)")
                st.toast(f"Ranked {len(task.result)} recovery opportunities", icon="✅")
            elif task.error:
                log_event("error", f"Planner failed: {task.error}")
                st.error(f"Planner error: {task.error}", icon=":material/cancel:")
            st.rerun()

    # ---- Sidebar ----
    with st.sidebar:
        st.markdown(":material/settings: **Pipeline Controls**")

        demo_mode = st.toggle(
            "Demo Mode",
            value=True,
            help="Pins the 5 hero scenarios (C001–C005) to the top of the queue",
        )

        st.divider()

        if not st.session_state.is_planning:
            if st.button("Run Planner", icon=":material/play_arrow:", type="primary", use_container_width=True):
                task = PlannerTask()
                st.session_state.planner_task = task
                st.session_state.is_planning  = True
                threading.Thread(target=_planner_worker, args=(task,), daemon=True).start()
                log_event("info", "Planner started")
                st.rerun()
        else:
            if st.button("Cancel Planner", icon=":material/stop_circle:", type="secondary", use_container_width=True):
                task = st.session_state.planner_task
                if task:
                    task.cancelled = True
                st.session_state.is_planning  = False
                st.session_state.planner_task = None
                log_event("warning", "Planner cancelled by user")
                st.rerun()

        has_leads = bool(st.session_state.leads)
        if st.button(
            "Personalize Hero Scenarios",
            icon=":material/bolt:",
            use_container_width=True,
            disabled=not has_leads or st.session_state.is_planning,
            help="Runs the Nurturer agent on the 5 demo scenarios in sequence",
        ):
            pending = [
                o for o in st.session_state.leads
                if o["customer_id"] in HERO_IDS
                and o["customer_id"] not in st.session_state.drafts
                and o["customer_id"] not in st.session_state.sent
            ]
            if not pending:
                st.info("All hero scenarios already have drafts.", icon=":material/info:")
            else:
                prog = st.progress(0, text="Starting batch…")
                for i, hero in enumerate(pending):
                    prog.progress(i / len(pending), text=f"Nurturing {hero['name']}…")
                    try:
                        draft, trace = run_nurturer(hero)
                        st.session_state.drafts[hero["customer_id"]] = {"draft": draft, "tool_trace": trace}
                        log_event("success", f"Draft ready: {hero['name']}")
                    except Exception as exc:
                        st.session_state.errors[hero["customer_id"]] = str(exc)
                        log_event("error", f"Nurturer error for {hero['name']}: {exc}")
                prog.progress(1.0, text="Batch complete!")
                time.sleep(0.4)
                st.rerun()

        st.divider()
        st.markdown(":material/bolt: **Simulate Shopify webhook**")
        st.caption("Mimics a `checkouts/abandoned` event from a live store.")
        if st.button("Inject test abandoned cart", icon=":material/webhook:", use_container_width=True,
                     disabled=st.session_state.is_planning):
            try:
                cart = simulate_incoming_cart()
                log_event("success", f"Webhook ingested cart {cart['cart_id']} (${cart['cart_value']:.0f})")
                st.toast(f"Ingested {cart['cart_id']} — re-run Planner to score it", icon="🛒")
            except Exception as exc:
                log_event("error", f"Webhook ingest failed: {exc}")
                st.toast("Ingest failed", icon="🚨")

        st.divider()
        st.caption(f"**Model** `{NURTURER_MODEL}`")
        st.caption(f"**DB** `{DB_NAME}`")
        st.caption(f"**Demo inbox** `{os.getenv('DEMO_TO_EMAIL', '—')}`")

        st.divider()
        log_col1, log_col2 = st.columns([7, 4])
        log_col1.markdown(":material/history: **Activity Log**")
        if log_col2.button("Clear", key="clear_log", icon=":material/delete_sweep:"):
            st.session_state.activity_log = []
            st.rerun()
        render_activity_log()

    # ---- Header ----
    st.markdown("## :material/savings: Morsegrid Outfitters — AI Revenue Recovery Agent")
    st.markdown(
        "Recovers **abandoned carts** + re-engages **dormant customers** &nbsp;·&nbsp; "
        "`Gemini 3 Flash` · `Google ADK` · `MongoDB MCP Server` · `Atlas Vector Search`"
    )
    st.divider()

    # ---- Planning in progress ----
    if st.session_state.is_planning:
        st.info("Scanning MongoDB for abandoned carts + dormant customers and scoring by expected value…",
                icon=":material/sync:")
        time.sleep(0.4)
        st.rerun()
        return

    # ---- Empty state ----
    if not st.session_state.leads:
        left, right = st.columns([3, 2])
        with left:
            st.info("Click **Run Planner** in the sidebar to find and rank revenue-recovery opportunities.",
                    icon=":material/info:")
            st.markdown("""
**How it works — four steps:**

**1 · Planner** — scans MongoDB for two kinds of lost revenue and ranks them in one queue:
> 🛒 **Abandoned carts** — `P(recover) × cart value × recency`
> 💤 **Dormant customers** — `P(convert) × margin × recency`

**2 · Nurturer** *(Gemini 3 Flash + ADK + MongoDB MCP)* — reads the shopper's behavior via
MCP `find`, runs Atlas Vector Search for the right products (the exact item, in-stock
alternatives, or a complement), and drafts a personalized message.

**3 · You review** — inspect every tool call in the Agent Reasoning Trace. Edit. Approve or reject.

**4 · Sender** — picks the best channel (email / SMS / IG DM), delivers, and logs to MongoDB.
            """)
        with right:
            st.markdown("#### Stack")
            st.markdown("""
| Component | Technology |
|-----------|-----------|
| Orchestration | Google ADK |
| LLM | Gemini 3 Flash |
| DB Operations | MongoDB MCP Server |
| Vector Search | Atlas + text-embedding-004 |
| Cart ingestion | Shopify-style webhook |
| Email Delivery | Resend API |
            """)
        return

    # ---- Metrics ----
    opps = st.session_state.leads
    cart_opps = [o for o in opps if o["opp_type"] == "abandoned_cart"]
    value_at_risk = sum(o.get("cart_value", 0) for o in cart_opps)
    sent_count = sum(1 for v in st.session_state.sent.values() if v.get("result") != "rejected")
    rejected_count = sum(1 for v in st.session_state.sent.values() if v.get("result") == "rejected")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Opportunities", len(opps))
    c2.metric("Abandoned Carts", len(cart_opps))
    c3.metric("Cart $ at Risk", f"${value_at_risk:,.0f}")
    c4.metric("Messages Sent", sent_count)
    c5.metric("Rejected", rejected_count)

    st.divider()

    with st.expander(":material/bar_chart: Full Opportunity Table — all ranked opportunities", expanded=False):
        st.markdown(scoring_table_md(opps))

    # ---- Display order ----
    if demo_mode:
        heroes  = [o for o in opps if o["customer_id"] in HERO_IDS]
        others  = [o for o in opps if o["customer_id"] not in HERO_IDS]
        # keep heroes in their natural EV order within the pinned group
        display = heroes + others
    else:
        display = opps

    max_ev = max((o["score"] for o in display), default=1)

    st.subheader("Revenue Recovery Queue")

    for rank, opp in enumerate(display[:9], 1):
        cid       = opp["customer_id"]
        is_hero   = cid in HERO_IDS
        has_draft = cid in st.session_state.drafts
        is_sent   = cid in st.session_state.sent
        has_error = cid in st.session_state.errors

        em, lbl     = status_chip(cid)
        seg_icon    = SEGMENT_ICONS.get(opp["segment"], ":material/person:")
        badge       = OPP_BADGE.get(opp["opp_type"], "")
        hero_prefix = ":material/star: " if (is_hero and demo_mode) else ""

        expander_label = (
            f"{hero_prefix}#{rank}  {opp['name']}  ·  {badge}  ·  "
            f"EV ${opp['score']}  ·  {em} {lbl}"
        )

        is_rejected  = is_sent and st.session_state.sent.get(cid, {}).get("result") == "rejected"
        force_open   = cid in st.session_state.force_expanded
        if force_open:
            st.session_state.force_expanded.discard(cid)
        with st.expander(expander_label, expanded=(rank <= 3 and not is_sent) or (has_draft and not is_sent) or is_rejected or force_open):

            if is_sent:
                sent_info = st.session_state.sent[cid]
                if sent_info.get("result") != "rejected":
                    ch       = sent_info.get("channel", "email")
                    ch_label = CHANNEL_LABELS.get(ch, ":material/mail: DELIVERED")
                    reason   = sent_info.get("channel_reason", "")
                    st.success(f"Delivered via **{ch_label}** — {reason}", icon=":material/check_circle:")
                else:
                    st.error("Draft rejected — message was not sent.", icon=":material/cancel:")

            # Opportunity context
            if opp["opp_type"] == "abandoned_cart":
                render_cart_card(opp)
                st.divider()
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("EV Score", f"${opp['score']}")
                mc2.metric("P(recover)", f"{opp['p_value']:.0%}")
                mc3.metric("Cart Value", f"${opp.get('cart_value', 0):.0f}")
                mc4.metric("Hours Cold", opp.get("hours_since_abandon"))
            else:
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("EV Score", f"${opp['score']}")
                mc2.metric("P(convert)", f"{opp['p_value']:.0%}")
                mc3.metric("Days Inactive", opp.get("days_inactive"))
                mc4.metric("Lifetime Orders", opp.get("total_orders", 0))

            ev_pct = min(opp["score"] / max_ev, 1.0) if max_ev > 0 else 0.0
            st.progress(ev_pct, text=f"EV: **${opp['score']}** / ${max_ev} top opportunity")
            st.caption(f"**Why this opportunity:** {opp['rationale']}")

            if opp.get("behavior_summary"):
                st.info(f"**Behavior signal:** {opp['behavior_summary']}", icon=":material/psychology:")

            ch_hint = "email" if opp.get("email_opens_last_30d", 0) >= 2 or not opp.get("sms_opted_in") else "SMS"
            st.markdown(f":material/mail: `{opp.get('email', '—')}` · likely channel: **{ch_hint}**")
            st.divider()

            # ---- Personalize ----
            if not has_draft and not is_sent:
                if has_error:
                    st.warning(f"Last attempt failed: `{st.session_state.errors[cid][:150]}`", icon=":material/warning:")
                    do_nurture = st.button("Retry Nurturer", icon=":material/refresh:", key=f"nurture_{cid}", type="secondary")
                else:
                    do_nurture = st.button("Personalize Message", icon=":material/smart_toy:", key=f"nurture_{cid}",
                                           type="secondary", help="Runs Nurturer — MCP behavior fetch + Atlas Vector Search")

                if do_nurture:
                    with st.status(f":material/sync: Nurturer working on {opp['name']}…", expanded=True) as nstatus:
                        st.write(":material/folder_open: Fetching behavior history from MongoDB via MCP `find`…")
                        st.write(":material/search: Running Atlas Vector Search for the right products…")
                        st.write(":material/edit_note: Drafting personalized message (Gemini 3 Flash)…")
                        try:
                            draft, tool_trace = run_nurturer(opp)
                            st.session_state.drafts[cid] = {"draft": draft, "tool_trace": tool_trace}
                            st.session_state.errors.pop(cid, None)
                            mcp_n = sum(1 for t in tool_trace if t.get("is_mcp"))
                            log_event("success", f"Draft ready: {opp['name']} ({mcp_n} MCP calls)")
                            nstatus.update(label=f":material/check_circle: Draft ready — {mcp_n} MCP calls",
                                           state="complete", expanded=False)
                            st.rerun()
                        except Exception as exc:
                            st.session_state.errors[cid] = str(exc)
                            log_event("error", f"Nurturer failed for {opp['name']}: {exc}")
                            nstatus.update(label=f":material/cancel: Nurturer error — {opp['name']}", state="error", expanded=True)
                            st.error(f"**Error:** {exc}", icon=":material/cancel:")
                            st.rerun()

            # ---- Draft view ----
            if has_draft:
                d          = st.session_state.drafts[cid]
                draft      = d["draft"]
                tool_trace = d.get("tool_trace", [])
                mcp_count  = sum(1 for t in tool_trace if t.get("is_mcp"))
                tool_count = len(tool_trace) - mcp_count

                with st.expander(
                    f":material/account_tree: Agent Reasoning Trace — {len(tool_trace)} tool calls "
                    f"({mcp_count} MCP · {tool_count} custom)", expanded=False):
                    render_trace(tool_trace)
                    recs = draft.get("recommended_product_ids", [])
                    if recs:
                        st.caption(f":material/shopping_cart: Vector search surfaced: **{', '.join(recs)}**")
                    st.caption("MCP calls are :blue[**blue**] (MongoDB). Custom tools are :green[**green**].")

                body_col, meta_col = st.columns([3, 1])
                with body_col:
                    st.markdown(f"**Subject:** {draft.get('subject', '—')}")
                    sent_ok = is_sent and st.session_state.sent.get(cid, {}).get("result") != "rejected"
                    st.text_area("Message body (editable before approval)", value=draft.get("body", ""),
                                 height=210, key=f"body_{cid}", disabled=sent_ok)
                with meta_col:
                    st.markdown("**Recommended**")
                    for pid in draft.get("recommended_product_ids", []):
                        st.markdown(f"- `{pid}`")

                # ---- Approve / Reject ----
                if not is_sent:
                    b_approve, b_reject, _ = st.columns([2, 2, 4])
                    with b_approve:
                        if st.button("Approve & Send", icon=":material/send:", key=f"approve_{cid}", type="primary"):
                            with st.status(f":material/sync: Sender delivering to {opp['name']}…", expanded=True) as sstatus:
                                st.write(":material/call_split: Selecting best channel via `pick_channel`…")
                                st.write(":material/upload: Sending message (Resend API / mock)…")
                                st.write(":material/save: Logging delivery to MongoDB…")
                                try:
                                    edited = {**draft, "body": st.session_state.get(f"body_{cid}", draft.get("body", ""))}
                                    result, sender_trace, channel, reason = _send_direct(opp, edited)
                                    ch_label = CHANNEL_LABELS.get(channel, ":material/mail: DELIVERED")
                                    st.session_state.sent[cid] = {
                                        "result": result, "channel": channel,
                                        "channel_reason": reason, "tool_trace": sender_trace,
                                    }
                                    del st.session_state.drafts[cid]
                                    st.session_state.pop(f"body_{cid}", None)
                                    log_event("success", f"Sent to {opp['name']} via {channel}")
                                    sstatus.update(label=f":material/check_circle: Delivered — {ch_label}",
                                                   state="complete", expanded=False)
                                    st.toast(f"Sent to {opp['name']} via {channel}!", icon="✅")
                                    st.rerun()
                                except Exception as exc:
                                    log_event("error", f"Sender failed for {opp['name']}: {exc}")
                                    sstatus.update(label=f":material/cancel: Sender error — {opp['name']}", state="error", expanded=True)
                                    st.error(f"**Sender error:** {exc}", icon=":material/cancel:")
                    with b_reject:
                        if st.button("Reject", icon=":material/block:", key=f"reject_{cid}"):
                            st.session_state.sent[cid] = {"result": "rejected", "tool_trace": []}
                            st.session_state.force_expanded.add(cid)
                            log_event("info", f"Rejected draft for {opp['name']}")
                            st.rerun()
                else:
                    sent_info    = st.session_state.sent[cid]
                    sender_trace = sent_info.get("tool_trace", [])
                    if sent_info.get("result") == "rejected":
                        r1, r2, _ = st.columns([2, 2, 4])
                        with r1:
                            if st.button("Edit & Re-approve", icon=":material/edit:", key=f"edit_{cid}", type="primary"):
                                del st.session_state.sent[cid]
                                st.rerun()
                        with r2:
                            if st.button("Regenerate", icon=":material/refresh:", key=f"regen_{cid}", type="secondary"):
                                del st.session_state.sent[cid]
                                del st.session_state.drafts[cid]
                                st.session_state.force_expanded.add(cid)
                                st.rerun()
                    else:
                        if sender_trace:
                            with st.expander(f":material/cell_tower: Sender Trace — {len(sender_trace)} tool calls", expanded=False):
                                render_trace(sender_trace)

            if is_sent and not has_draft and st.session_state.sent.get(cid, {}).get("result") != "rejected":
                if st.button("Personalize New Message", icon=":material/smart_toy:", key=f"renew_{cid}", type="secondary"):
                    del st.session_state.sent[cid]
                    st.rerun()


if __name__ == "__main__":
    main()
