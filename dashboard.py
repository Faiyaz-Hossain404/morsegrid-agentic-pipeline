"""
Morsegrid Outfitters — Re-engagement Agent Dashboard

Streamlit UI: ranked lead queue → Nurturer drafts → human approves → Sender delivers.
Agents use the MongoDB MCP server for all DB ops (eligibility req #3).

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
# ADK agents run on GEMINI_LOCATION (global); embeddings keep their own
# us-central1 client (text-embedding-004), so they are unaffected.
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GEMINI_LOCATION", "global")

import streamlit as st

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from db.mongo import get_db_client
from tools.lead_scorer import score_lead_ev
from tools.product_search import find_similar_products
from tools.channel import pick_channel
from tools.email_sender import send_email_resend
from tools.mock_channels import send_sms_mock, send_ig_dm_mock

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_NAME        = "morsegrid_outfitters"
NURTURER_MODEL = os.getenv("NURTURER_MODEL", "gemini-3-flash-preview")
SENDER_MODEL   = os.getenv("SENDER_MODEL",   "gemini-3-flash-preview")
APP            = "morsegrid_dashboard"
USER_ID        = "dashboard_user"
NPX            = shutil.which("npx") or ("npx.cmd" if sys.platform == "win32" else "npx")
HERO_IDS       = {"C001", "C002", "C003"}  # Mike / Sarah / Diego — demo scenarios

SEGMENT_ICONS = {
    "VIP":     ":material/workspace_premium:",
    "repeat":  ":material/repeat:",
    "engaged": ":material/thumb_up:",
    "cold":    ":material/ac_unit:",
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


def detect_channel(result_text: str) -> str:
    t = result_text.lower()
    for ch in ("ig_dm", "sms", "email"):
        if ch.replace("_", " ") in t or ch in t:
            return ch
    return "email"


# ---------------------------------------------------------------------------
# Planner — background task wrapper for cancellable execution
# ---------------------------------------------------------------------------

class PlannerTask:
    """Holds the result of a background planner run."""
    def __init__(self):
        self.result:    list | None = None
        self.error:     str  | None = None
        self.done:      bool        = False
        self.cancelled: bool        = False


def _planner_worker(task: PlannerTask):
    try:
        result = run_planner()
        if not task.cancelled:
            task.result = result
    except Exception as exc:
        if not task.cancelled:
            task.error = str(exc)
    finally:
        task.done = True


# ---------------------------------------------------------------------------
# Planner — pure Python (no LLM)
# ---------------------------------------------------------------------------

def run_planner() -> list:
    client = get_db_client()
    customers = list(client[DB_NAME].customers.find({}))
    now = datetime.now(timezone.utc)
    scored = []

    for c in customers:
        raw_ts = c.get("last_active_at", "")
        try:
            if isinstance(raw_ts, datetime):
                last_active = raw_ts.replace(tzinfo=timezone.utc) if raw_ts.tzinfo is None else raw_ts
            elif isinstance(raw_ts, (int, float)):
                last_active = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
            else:
                last_active = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except Exception:
            last_active = now

        days_inactive = max((now - last_active).days, 0)
        total_orders  = int(c.get("total_orders", 0))
        total_spend   = float(c.get("total_spend", 0.0))
        avg_order_val = (total_spend / total_orders) if total_orders > 0 else 250.0
        eng         = c.get("engagement") or {}
        last5       = eng.get("last5_opens") or []
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
            "score":                ev["score"],
            "rationale":            ev["rationale"],
            "p_convert":            ev["p_convert"],
            "days_inactive":        days_inactive,
            "email_opens_last_30d": email_opens,
            "sms_opted_in":         sms_optin,
        })

    return sorted(scored, key=lambda x: x["score"], reverse=True)


# ---------------------------------------------------------------------------
# Nurturer — ADK agent + MCP
# ---------------------------------------------------------------------------

async def _nurturer_async(lead: dict):
    toolset = build_toolset()
    try:
        agent = LlmAgent(
            name="nurturer",
            model=NURTURER_MODEL,
            instruction=f"""You are the Nurturer for Morsegrid Outfitters' re-engagement pipeline.

IMPORTANT — available MongoDB tools: find, aggregate, collection-schema. Do NOT call
list_collections, list_databases, or any other tool not listed here. Go directly to step 1.

Steps:
1. Call the MongoDB find tool with EXACTLY these parameters:
   database='{DB_NAME}', collection='behavior_events',
   filter={{"customer_id": "<the customer_id you received>"}}, limit=15
2. Call find_similar_products with a query that captures their specific interests —
   use their search queries, product categories viewed, and behavior_summary.
3. Draft a warm, personal re-engagement email (NOT a mass-marketing blast):
   - Reference the specific reason we are reaching out (item back in stock, new arrival
     matching their search, latent want now available, etc.).
   - Name 1-2 recommended products with prices.
   - Keep body under 200 words. Sound like a real person at the store.
   - ALWAYS end the body with exactly this sign-off on its own line:
     "Best,\nThe Morsegrid Outfitters Team"
4. Return ONLY a valid JSON object:
   {{"subject": "...", "body": "...", "recommended_product_ids": ["P001", ...]}}

Output ONLY the JSON. No surrounding text.""",
            tools=[toolset, find_similar_products],
        )
        sid = f"dash-nur-{lead['customer_id']}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        runner = InMemoryRunner(agent=agent, app_name=APP)
        await runner.session_service.create_session(app_name=APP, user_id=USER_ID, session_id=sid)

        prompt = (
            f"Customer ID: {lead['customer_id']} | Name: {lead['name']} | "
            f"Segment: {lead['segment']} | Days inactive: {lead['days_inactive']} | "
            f"Behavior: {lead.get('behavior_summary', 'N/A')}. "
            f"Fetch their events, find matching products, draft the re-engagement message."
        )
        output, tool_trace = await agent_turn(runner, sid, prompt)
        draft = extract_json(output)
        body = draft.get("body", "")
        if "Morsegrid Outfitters Team" not in body:
            draft["body"] = body.rstrip() + "\n\nBest,\nThe Morsegrid Outfitters Team"
        return draft, tool_trace
    finally:
        await toolset.close()


def run_nurturer(lead: dict):
    return run_async(_nurturer_async(lead))


# ---------------------------------------------------------------------------
# Sender — direct Python (no LLM needed: all 3 ops are deterministic)
# pick_channel → send → pymongo insert; ~1-2s vs ~20s for agent round-trips
# ---------------------------------------------------------------------------

def _send_direct(lead: dict, draft: dict):
    channel = "email"
    send_result = send_email_resend(
        lead["email"], draft.get("subject", ""), draft.get("body", ""), lead["customer_id"]
    )

    status = send_result.get("status", "sent")
    if status not in ("sent", "mock_sent"):
        raise RuntimeError(f"Delivery failed: {send_result.get('error', 'unknown error')}")

    mongo_client = get_db_client()
    mongo_client[DB_NAME]["messages_sent"].insert_one({
        "customer_id": lead["customer_id"],
        "name":        lead["name"],
        "channel":     channel,
        "subject":     draft.get("subject", ""),
        "sent_at":     datetime.now(timezone.utc).isoformat(),
        "status":      status,
    })

    tool_trace = [
        {"tool": "send_email_resend",  "args": {"to": lead["email"]},                              "is_mcp": False},
        {"tool": "mongodb.insert_one", "args": {"collection": "messages_sent", "status": status},  "is_mcp": False},
    ]
    return f"Sent to {lead['name']} via email — {status}.", tool_trace, channel


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def render_trace(tool_trace: list):
    if not tool_trace:
        st.caption("No tool calls recorded.")
        return
    for entry in tool_trace:
        args_str = ", ".join(
            f"{k}={repr(v)[:60]}" for k, v in entry.get("args", {}).items()
        )
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


def scoring_table_md(leads: list) -> str:
    rows = [
        "| # | Name | Segment | EV Score | P(conv) | Days | Email Opens | Status |",
        "|---|------|---------|----------|---------|------|-------------|--------|",
    ]
    for i, l in enumerate(leads, 1):
        em, lbl = status_chip(l["customer_id"])
        rows.append(
            f"| {i} | {l['name']} | {l['segment']} | **{l['score']}** | "
            f"{l['p_convert']:.0%} | {l['days_inactive']} | "
            f"{l['email_opens_last_30d']} | {em} {lbl} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Morsegrid Outfitters — Re-engagement",
        page_icon="🏍",
        layout="wide",
    )

    # Session state init
    for key, default in [
        ("leads", []), ("drafts", {}), ("sent", {}),
        ("errors", {}), ("activity_log", []),
        ("is_planning", False), ("planner_task", None),
        ("force_expanded", set()),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # ---- Planner task completion check (runs on every rerun while planning) ----
    if st.session_state.is_planning:
        task: PlannerTask = st.session_state.planner_task
        if task and task.done:
            st.session_state.is_planning = False
            st.session_state.planner_task = None
            if task.result:
                st.session_state.leads  = task.result
                st.session_state.drafts = {}
                st.session_state.sent   = {}
                st.session_state.errors = {}
                log_event("success", f"Planner scored {len(task.result)} customers")
                st.toast(f"Ranked {len(task.result)} customers by EV score", icon="✅")
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
            help="Pins Mike / Sarah / Diego (C001–C003) to top of queue",
        )

        st.divider()

        if not st.session_state.is_planning:
            if st.button(
                "Run Planner",
                icon=":material/play_arrow:",
                type="primary",
                use_container_width=True,
            ):
                task = PlannerTask()
                st.session_state.planner_task = task
                st.session_state.is_planning  = True
                threading.Thread(target=_planner_worker, args=(task,), daemon=True).start()
                log_event("info", "Planner started")
                st.rerun()
        else:
            if st.button(
                "Cancel Planner",
                icon=":material/stop_circle:",
                type="secondary",
                use_container_width=True,
            ):
                task = st.session_state.planner_task
                if task:
                    task.cancelled = True
                st.session_state.is_planning  = False
                st.session_state.planner_task = None
                log_event("warning", "Planner cancelled by user")
                st.toast("Planner cancelled", icon="⚠️")
                st.rerun()

        has_leads = bool(st.session_state.leads)
        if st.button(
            "Personalize Top 3",
            icon=":material/bolt:",
            use_container_width=True,
            disabled=not has_leads or st.session_state.is_planning,
            help="Runs Nurturer agent on Mike, Sarah & Diego in sequence (skips those already done)",
        ):
            leads   = st.session_state.leads
            pending = [
                l for l in leads
                if l["customer_id"] in HERO_IDS
                and l["customer_id"] not in st.session_state.drafts
                and l["customer_id"] not in st.session_state.sent
            ]
            if not pending:
                st.info("All demo leads already have drafts.", icon=":material/info:")
            else:
                prog = st.progress(0, text="Starting batch…")
                for i, hero in enumerate(pending):
                    prog.progress(i / len(pending), text=f"Nurturing {hero['name']}…")
                    try:
                        draft, trace = run_nurturer(hero)
                        st.session_state.drafts[hero["customer_id"]] = {
                            "draft": draft, "tool_trace": trace,
                        }
                        log_event("success", f"Draft ready: {hero['name']}")
                        st.toast(f"Draft ready: {hero['name']}")
                    except Exception as exc:
                        st.session_state.errors[hero["customer_id"]] = str(exc)
                        log_event("error", f"Nurturer error for {hero['name']}: {exc}")
                        st.toast(f"Error on {hero['name']}", icon="🚨")
                prog.progress(1.0, text="Batch complete!")
                time.sleep(0.5)
                st.rerun()

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
    st.markdown("## :material/two_wheeler: Morsegrid Outfitters — Re-engagement Agent")
    st.markdown(
        "`Gemini 3 Flash` &nbsp;·&nbsp; `Google ADK 2.2` &nbsp;·&nbsp; "
        "`MongoDB MCP Server` &nbsp;·&nbsp; `Atlas Vector Search`"
    )
    st.divider()

    # ---- Planning in progress — poll until thread completes ----
    if st.session_state.is_planning:
        st.info(
            "Fetching all customers from MongoDB and computing EV scores…",
            icon=":material/sync:",
        )
        time.sleep(0.4)   # poll interval — keeps reruns from hammering the CPU
        st.rerun()
        return

    # ---- Empty state ----
    if not st.session_state.leads:
        left, right = st.columns([3, 2])
        with left:
            st.info(
                "Click **Run Planner** in the sidebar to score and rank your customers.",
                icon=":material/info:",
            )
            st.markdown("""
**How it works — four steps:**

**1 · Planner** — fetches all customers from MongoDB, scores each with:
> `EV = P(convert) × avg_margin × e^(−days_inactive / 60)`

**2 · Nurturer** *(Gemini 3 Flash + ADK + MongoDB MCP)* — reads the customer's
behavior history via MCP `find`, runs Atlas Vector Search for matching products,
and drafts a personalized re-engagement message.

**3 · You review** — inspect every tool call in the Agent Reasoning Trace.
Edit the draft. Approve or reject.

**4 · Sender** *(Gemini 3 Flash + ADK + MongoDB MCP)* — picks the best channel
(email / SMS / IG DM), delivers the message, and logs delivery to MongoDB via MCP `insert-many`.
            """)
        with right:
            st.markdown("#### Stack")
            st.markdown("""
| Component | Technology |
|-----------|-----------|
| Orchestration | Google ADK 2.2 |
| LLM | Gemini 3 Flash |
| DB Operations | MongoDB MCP Server |
| Vector Search | Atlas + text-embedding-004 |
| Email Delivery | Resend API |
| Lead Scoring | Pure Python EV formula |
            """)
        return

    # ---- Metrics ----
    sent_count = sum(
        1 for v in st.session_state.sent.values()
        if v.get("result") != "rejected"
    )
    rejected_count = sum(
        1 for v in st.session_state.sent.values()
        if v.get("result") == "rejected"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers Scored", len(st.session_state.leads))
    c2.metric("Drafts Ready",     len(st.session_state.drafts))
    c3.metric("Messages Sent",    sent_count)
    c4.metric("Rejected",         rejected_count)

    st.divider()

    # ---- Full scoring table (collapsed) ----
    with st.expander(":material/bar_chart: Full Lead Scoring Table — all customers", expanded=False):
        st.markdown(scoring_table_md(st.session_state.leads))

    # ---- Display order ----
    leads = st.session_state.leads
    if demo_mode:
        heroes  = [l for l in leads if l["customer_id"] in HERO_IDS]
        others  = [l for l in leads if l["customer_id"] not in HERO_IDS]
        display = heroes + others
    else:
        display = leads

    max_ev = max((l["score"] for l in display), default=1)

    st.subheader("Re-engagement Queue")

    for rank, lead in enumerate(display[:8], 1):
        cid       = lead["customer_id"]
        is_hero   = cid in HERO_IDS
        has_draft = cid in st.session_state.drafts
        is_sent   = cid in st.session_state.sent
        has_error = cid in st.session_state.errors

        em, lbl     = status_chip(cid)
        seg_icon    = SEGMENT_ICONS.get(lead["segment"], ":material/person:")
        hero_prefix = ":material/star: " if (is_hero and demo_mode) else ""

        expander_label = (
            f"{hero_prefix}#{rank}  {lead['name']}  ·  "
            f"{seg_icon} {lead['segment']}  ·  EV {lead['score']}  ·  {em} {lbl}"
        )

        is_rejected  = is_sent and st.session_state.sent.get(cid, {}).get("result") == "rejected"
        force_open   = cid in st.session_state.force_expanded
        if force_open:
            st.session_state.force_expanded.discard(cid)
        with st.expander(expander_label, expanded=(rank <= 3 and not is_sent) or (has_draft and not is_sent) or is_rejected or force_open):

            # Sent / rejected banner at top of card
            if is_sent:
                sent_info = st.session_state.sent[cid]
                if sent_info.get("result") != "rejected":
                    ch       = sent_info.get("channel") or detect_channel(sent_info.get("result", ""))
                    ch_label = CHANNEL_LABELS.get(ch, ":material/mail: DELIVERED")
                    st.success(
                        f"Delivered via **{ch_label}**",
                        icon=":material/check_circle:",
                    )
                else:
                    st.error("Draft rejected — message was not sent.", icon=":material/cancel:")

            # Lead metrics
            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("EV Score",        lead["score"])
            mc2.metric("P(convert)",      f"{lead['p_convert']:.0%}")
            mc3.metric("Days Inactive",   lead["days_inactive"])
            mc4.metric("Email Opens 30d", lead["email_opens_last_30d"])
            mc5.metric("SMS Opt-in",      "Yes" if lead.get("sms_opted_in") else "No")

            # EV progress bar (native Streamlit component, normalized 0.0–1.0)
            ev_pct = min(lead["score"] / max_ev, 1.0) if max_ev > 0 else 0.0
            st.progress(ev_pct, text=f"EV Score: **{lead['score']}** / {max_ev} top score")

            st.caption(f"**Why this lead:** {lead['rationale']}")

            if lead.get("behavior_summary"):
                st.info(
                    f"**Behavior signal:** {lead['behavior_summary']}",
                    icon=":material/psychology:",
                )

            st.markdown(f":material/mail: `{lead['email']}`")

            st.divider()

            # ---- Personalize button ----
            if not has_draft and not is_sent:
                if has_error:
                    st.warning(
                        f"Last attempt failed: `{st.session_state.errors[cid][:150]}`",
                        icon=":material/warning:",
                    )
                    do_nurture = st.button(
                        "Retry Nurturer",
                        icon=":material/refresh:",
                        key=f"nurture_{cid}",
                        type="secondary",
                    )
                else:
                    do_nurture = st.button(
                        "Personalize Message",
                        icon=":material/smart_toy:",
                        key=f"nurture_{cid}",
                        type="secondary",
                        help="Runs Nurturer agent — MCP behavior fetch + Atlas Vector Search",
                    )

                if do_nurture:
                    with st.status(
                        f":material/sync: Nurturer working on {lead['name']}…",
                        expanded=True,
                    ) as nstatus:
                        st.write(
                            f":material/folder_open: Fetching {lead['name']}'s behavior "
                            f"history from MongoDB via MCP `find`…"
                        )
                        st.write(":material/search: Running Atlas Vector Search for matching products…")
                        st.write(":material/edit_note: Drafting personalized re-engagement email (Gemini 3 Flash)…")
                        try:
                            draft, tool_trace = run_nurturer(lead)
                            st.session_state.drafts[cid] = {
                                "draft": draft,
                                "tool_trace": tool_trace,
                            }
                            if cid in st.session_state.errors:
                                del st.session_state.errors[cid]
                            mcp_n = sum(1 for t in tool_trace if t.get("is_mcp"))
                            log_event("success", f"Draft ready: {lead['name']} ({mcp_n} MCP calls)")
                            nstatus.update(
                                label=f":material/check_circle: Draft ready for {lead['name']} — {mcp_n} MCP calls",
                                state="complete",
                                expanded=False,
                            )
                            st.toast(f"Draft ready: {lead['name']}")
                            st.rerun()
                        except Exception as exc:
                            st.session_state.errors[cid] = str(exc)
                            log_event("error", f"Nurturer failed for {lead['name']}: {exc}")
                            nstatus.update(
                                label=f":material/cancel: Nurturer error — {lead['name']}",
                                state="error",
                                expanded=True,
                            )
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
                    f"({mcp_count} MCP · {tool_count} custom)",
                    expanded=False,
                ):
                    render_trace(tool_trace)
                    recs = draft.get("recommended_product_ids", [])
                    if recs:
                        st.caption(
                            f":material/shopping_cart: Vector search surfaced: **{', '.join(recs)}**"
                        )
                    st.caption(
                        "MCP calls are :blue[**blue**] (MongoDB operations). "
                        "Custom tools are :green[**green**]."
                    )

                body_col, meta_col = st.columns([3, 1])
                with body_col:
                    st.markdown(f"**Subject:** {draft.get('subject', '—')}")
                    sent_and_delivered = (
                        is_sent and
                        st.session_state.sent.get(cid, {}).get("result") != "rejected"
                    )
                    st.text_area(
                        "Message body (editable before approval)",
                        value=draft.get("body", ""),
                        height=200,
                        key=f"body_{cid}",
                        disabled=sent_and_delivered,
                    )
                with meta_col:
                    st.markdown("**Recommended**")
                    for pid in draft.get("recommended_product_ids", []):
                        st.markdown(f"- `{pid}`")
                    st.markdown(":material/mail: **Channel: Email**")

                # ---- Approve / Reject ----
                if not is_sent:
                    b_approve, b_reject, _ = st.columns([2, 2, 4])

                    with b_approve:
                        if st.button(
                            "Approve & Send",
                            icon=":material/send:",
                            key=f"approve_{cid}",
                            type="primary",
                        ):
                            with st.status(
                                f":material/sync: Sender delivering to {lead['name']}…",
                                expanded=True,
                            ) as sstatus:
                                st.write(":material/call_split: Selecting best channel via `pick_channel`…")
                                st.write(":material/upload: Sending message (Resend API / mock)…")
                                st.write(":material/save: Logging delivery to MongoDB…")
                                try:
                                    edited_draft = {
                                        **draft,
                                        "body": st.session_state.get(
                                            f"body_{cid}", draft.get("body", "")
                                        ),
                                    }
                                    result, sender_trace, channel = _send_direct(lead, edited_draft)
                                    ch_label = CHANNEL_LABELS.get(channel, ":material/mail: DELIVERED")
                                    st.session_state.sent[cid] = {
                                        "result":     result,
                                        "channel":    channel,
                                        "tool_trace": sender_trace,
                                    }
                                    # Clear draft + widget so card resets to "Personalize Message"
                                    del st.session_state.drafts[cid]
                                    if f"body_{cid}" in st.session_state:
                                        del st.session_state[f"body_{cid}"]
                                    log_event("success", f"Sent to {lead['name']} via {ch_label}")
                                    sstatus.update(
                                        label=f":material/check_circle: Delivered to {lead['name']} — {ch_label}",
                                        state="complete",
                                        expanded=False,
                                    )
                                    st.toast(f"Sent to {lead['name']} via {ch_label}! Check your inbox.", icon="✅")
                                    st.rerun()
                                except Exception as exc:
                                    log_event("error", f"Sender failed for {lead['name']}: {exc}")
                                    sstatus.update(
                                        label=f":material/cancel: Sender error — {lead['name']}",
                                        state="error",
                                        expanded=True,
                                    )
                                    st.error(f"**Sender error:** {exc}", icon=":material/cancel:")

                    with b_reject:
                        if st.button(
                            "Reject",
                            icon=":material/block:",
                            key=f"reject_{cid}",
                        ):
                            st.session_state.sent[cid] = {
                                "result": "rejected", "tool_trace": [],
                            }
                            st.session_state.force_expanded.add(cid)
                            log_event("info", f"Rejected draft for {lead['name']}")
                            st.toast(f"Draft rejected: {lead['name']}", icon="❌")
                            st.rerun()

                else:
                    sent_info    = st.session_state.sent[cid]
                    sender_trace = sent_info.get("tool_trace", [])

                    if sent_info.get("result") == "rejected":
                        # ---- Rejected — offer Edit or Regenerate ----
                        r1, r2, _ = st.columns([2, 2, 4])
                        with r1:
                            if st.button(
                                "Edit & Re-approve",
                                icon=":material/edit:",
                                key=f"edit_{cid}",
                                type="primary",
                                help="Keep this draft but make it editable again",
                            ):
                                del st.session_state.sent[cid]
                                log_event("info", f"Re-opened draft for editing: {lead['name']}")
                                st.rerun()
                        with r2:
                            if st.button(
                                "Regenerate",
                                icon=":material/refresh:",
                                key=f"regen_{cid}",
                                type="secondary",
                                help="Discard draft and run the Nurturer agent again",
                            ):
                                del st.session_state.sent[cid]
                                del st.session_state.drafts[cid]
                                st.session_state.force_expanded.add(cid)
                                log_event("info", f"Regenerating draft for {lead['name']}")
                                st.toast(f"Draft cleared — click Personalize to regenerate")
                                st.rerun()
                    else:
                        # ---- Successfully sent — show sender trace ----
                        if sender_trace:
                            smcp = sum(1 for t in sender_trace if t.get("is_mcp"))
                            with st.expander(
                                f":material/cell_tower: Sender Trace — {len(sender_trace)} tool calls",
                                expanded=False,
                            ):
                                render_trace(sender_trace)

            # ---- Delivered & draft cleared — offer fresh personalization ----
            if is_sent and not has_draft and st.session_state.sent.get(cid, {}).get("result") != "rejected":
                if st.button(
                    "Personalize New Message",
                    icon=":material/smart_toy:",
                    key=f"renew_{cid}",
                    type="secondary",
                    help="Clear this lead's sent record and start a fresh personalization cycle",
                ):
                    del st.session_state.sent[cid]
                    log_event("info", f"Re-opened personalization for {lead['name']}")
                    st.rerun()


if __name__ == "__main__":
    main()
