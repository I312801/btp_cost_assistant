"""
BTP Usage Agent — A2A-compatible entry point.

Accepts any JSON-RPC 2.0 method so no platform-side method name change can break it.
Supported methods (handled identically): message/send, tasks/send, tasks/sendSubscribe,
message/stream, and any future variants.
"""

import os
import uuid
import logging

# Load .env FIRST — must happen before any local imports that read env vars
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from agent import BTPUsageAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="BTP Usage Agent")

# Instantiate agent — never crash the server on init failure
try:
    btp_agent = BTPUsageAgent()
    logger.info("BTPUsageAgent initialised successfully")
except Exception as _init_err:
    logger.warning("BTPUsageAgent init skipped: %s", _init_err)
    btp_agent = None

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------
AGENT_CARD = {
    "name": "BTP Usage Agent",
    "version": "1.0.0",
    "description": (
        "Monitors SAP BTP account usage, costs, and entitlements across subaccounts. "
        "Ask: 'What are my top services by cost?' or 'Show subaccount usage.'"
    ),
    "url": os.getenv("AGENT_URL", ""),
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "btp-usage-query",
            "name": "BTP Usage Query",
            "description": "Query BTP service consumption and cost data for a subaccount or globally",
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        },
        {
            "id": "entitlement-check",
            "name": "Entitlement Check",
            "description": "Check entitlement utilization and flag quota gaps",
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        },
        {
            "id": "cost-breakdown",
            "name": "Cost Breakdown",
            "description": "Break down BTP costs by service, plan, and subaccount",
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        },
    ],
    "authentication": {"schemes": ["bearer"]},
}

# ---------------------------------------------------------------------------
# Health / discovery
# ---------------------------------------------------------------------------

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.get("/health")
async def health():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# A2A message endpoints — catch all paths the platform might call
# ---------------------------------------------------------------------------

@app.post("/")
async def handle_root(request: Request):
    return await _dispatch(request)

@app.post("/tasks/send")
async def handle_tasks_send(request: Request):
    return await _dispatch(request)

@app.post("/message/send")
async def handle_message_send(request: Request):
    return await _dispatch(request)

@app.post("/messages/send")
async def handle_messages_send(request: Request):
    return await _dispatch(request)

# ---------------------------------------------------------------------------
# Unified dispatcher — accepts ANY format / method
# ---------------------------------------------------------------------------

async def _dispatch(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error: body is not valid JSON")

    method = body.get("method", "")
    rpc_id = body.get("id")
    logger.info("Incoming request — method=%r rpc_id=%r path=%s", method, rpc_id, request.url.path)

    # ── JSON-RPC 2.0 envelope ────────────────────────────────────────────
    if "jsonrpc" in body or "method" in body:
        params = body.get("params") or {}

        # Extract message object — different specs put it in different places
        message = (
            params.get("message")          # A2A v0.2: params.message
            or params.get("task", {}).get("message")  # some variants
            or params                       # fallback: treat whole params as message
        )

        # Extract task / message ID
        task_id = (
            params.get("id")
            or params.get("messageId")
            or (message.get("messageId") if isinstance(message, dict) else None)
            or str(uuid.uuid4())
        )

        logger.info("Routing JSON-RPC method=%r task_id=%s", method, task_id)
        return await _run_task(rpc_id, task_id, message if isinstance(message, dict) else {})

    # ── Direct task body (no JSON-RPC wrapper) ───────────────────────────
    if "message" in body or "id" in body:
        task_id = body.get("id") or body.get("messageId") or str(uuid.uuid4())
        message = body.get("message", {})
        logger.info("Routing direct task body task_id=%s", task_id)
        return await _run_task(None, task_id, message)

    # ── Unknown format — treat entire body as text ───────────────────────
    raw = str(body)
    logger.warning("Unknown request format, forwarding as text: %.200s", raw)
    reply = await _invoke_agent(raw)
    return JSONResponse(content={"reply": reply})

# ---------------------------------------------------------------------------
# Core task runner
# ---------------------------------------------------------------------------

async def _run_task(rpc_id, task_id: str, message: dict):
    parts = message.get("parts", [])
    user_text = " ".join(
        p.get("text", "") for p in parts if p.get("type") == "text"
    ).strip()

    if not user_text:
        user_text = message.get("text", "")

    if not user_text:
        user_text = message.get("content", "")

    logger.info("Task %s — input: %.150s", task_id, user_text)

    reply_text = await _invoke_agent(user_text)

    result = {
        "id": task_id,
        "status": {
            "state": "completed",
            "message": {
                "role": "agent",
                "parts": [{"type": "text", "text": reply_text}],
            },
        },
    }

    if rpc_id is not None:
        return JSONResponse(content={"jsonrpc": "2.0", "id": rpc_id, "result": result})
    return JSONResponse(content=result)

async def _invoke_agent(user_text: str) -> str:
    if btp_agent is None:
        return (
            "The BTP Usage Agent failed to initialise. "
            "Please verify that BTP_UAS_URL, BTP_CLIENT_ID, BTP_CLIENT_SECRET, "
            "and BTP_GLOBAL_ACCOUNT_ID are set correctly."
        )
    try:
        return await btp_agent.run(user_text)
    except Exception as exc:
        logger.exception("Agent error")
        return f"An error occurred: {exc}"

def _error_response(rpc_id, code: int, message: str):
    return JSONResponse(
        status_code=200,
        content={"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}},
    )

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
