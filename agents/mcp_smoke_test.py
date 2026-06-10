"""Day-1 Pass Gate B: prove a Gemini 3 agent can drive the MongoDB MCP server.

Spins up MongoDB's official MCP server (`mongodb-mcp-server`, via npx) as a
subprocess, wires it into a minimal Gemini 3 ADK agent through `MCPToolset`,
and asks a question that forces a real MongoDB tool call. Prints the tool calls
(the eligibility evidence) and the agent's answer.

This is the partner-integration linchpin: the agent touches MongoDB ONLY through
the MCP server.

Run:  venv/Scripts/python.exe agents/mcp_smoke_test.py
"""
import os
import sys
import asyncio
import shutil

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

# ADK must reach Gemini 3 on Vertex AI using your ADC + project/location.
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

# Gemini 3 Flash — served from the `global` Vertex endpoint.
# Override via GEMINI_MODEL env var if needed.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
DB_NAME = "morsegrid_outfitters"
APP, USER, SESSION = "morsegrid_smoke", "faiyaz", "smoke-1"

# On Windows, npx resolves to npx.cmd — let shutil find the real path.
NPX = shutil.which("npx") or ("npx.cmd" if sys.platform == "win32" else "npx")


def build_toolset():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI missing from .env")
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=NPX,
                args=["-y", "mongodb-mcp-server"],
                # Pass via env var — preferred over the deprecated --connectionString flag
                env={**os.environ, "MDB_MCP_CONNECTION_STRING": uri},
            ),
            # generous: first run downloads the npx package + connects to Atlas
            timeout=120,
        ),
    )


async def main():
    print(f"Model: {MODEL} | project: {os.getenv('GOOGLE_CLOUD_PROJECT')} "
          f"| location: {os.getenv('GOOGLE_CLOUD_LOCATION')} | npx: {NPX}")
    toolset = build_toolset()
    agent = LlmAgent(
        name="db_smoke",
        model=MODEL,
        instruction=(
            f"You are a data assistant for an e-commerce store. All data lives in the "
            f"MongoDB database named '{DB_NAME}'. Collections: customers, products, "
            f"behavior_events, orders, messages_sent. Use the available MongoDB tools to "
            f"answer with a precise number — do not guess. Always pass database='{DB_NAME}'."
        ),
        tools=[toolset],
    )
    runner = InMemoryRunner(agent=agent, app_name=APP)
    await runner.session_service.create_session(app_name=APP, user_id=USER, session_id=SESSION)

    question = "How many customers are in the database?"
    print(f"\nQ: {question}\n")
    msg = types.Content(role="user", parts=[types.Part(text=question)])

    tool_calls, final_text = [], []
    try:
        async for event in runner.run_async(user_id=USER, session_id=SESSION, new_message=msg):
            content = getattr(event, "content", None)
            for part in (getattr(content, "parts", None) or []):
                fc = getattr(part, "function_call", None)
                if fc:
                    tool_calls.append(fc.name)
                    args = dict(fc.args) if getattr(fc, "args", None) else {}
                    print(f"  [MCP tool call] {fc.name}  args={args}")
                fr = getattr(part, "function_response", None)
                if fr:
                    print(f"  [tool result]   {fr.name} -> {str(fr.response)[:200]}")
                txt = getattr(part, "text", None)
                if txt and event.is_final_response():
                    final_text.append(txt)
    finally:
        await toolset.close()

    print("\n----- RESULT -----")
    print("AGENT ANSWER:", "".join(final_text).strip() or "(no text)")
    print("MCP TOOLS CALLED:", ", ".join(tool_calls) if tool_calls else "NONE")
    if tool_calls:
        print("DONE - Gemini 3 agent invoked the MongoDB MCP server  <-- DAY 1 PASS GATE B")
    else:
        print("WARN - no MCP tool was called; check model id / tool wiring")


if __name__ == "__main__":
    asyncio.run(main())
