# ââ sys.path bootstrap ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
# The platform's build pipeline installs pip packages to /app/dependencies/
# (builder stage) and copies them to the final image via custom_build.sh.
# We add that path here so Python can find packages like generative-ai-hub-sdk
# that are NOT pre-installed in the platform base image.
import sys as _sys
import os as _os
_deps_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "dependencies")
if not _os.path.isdir(_deps_path):
    _deps_path = "/app/dependencies"
if _os.path.isdir(_deps_path) and _deps_path not in _sys.path:
    _sys.path.insert(0, _deps_path)
# âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

"""
BTP Usage Agent â A2A-compatible entry point.

Accepts any JSON-RPC 2.0 method so no platform-side method name change can break it.
Supported methods (handled identically): message/send, tasks/send, tasks/sendSubscribe,
message/stream, and any future variants.
"""

import os
import uuid
import logging

# Load .env FIRST â must happen before any local imports that read env vars
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s â %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="BTP Usage Agent")

# Lazy import + instantiate agent â never crash the server on any error
btp_agent = None
try:
    from agent import BTPUsageAgent
    btp_agent = BTPUsageAgent()
    logger.info("BTPUsageAgent initialised successfully")
except Exception as _init_err:
    logger.warning("BTPUsageAgent init skipped: %s", _init_err)

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
# LLM diagnostics â GET /debug/llm
# ---------------------------------------------------------------------------

@app.get("/debug/llm")
async def debug_llm():
    """
    Diagnostic endpoint that checks the full LLM call chain:
      1. Which backend is configured (joule / aicore / openai)
      2. Which credentials are present (masked)
      3. Whether the platform secret mount contains AICORE files
      4. Whether a live LLM ping succeeds (sends a minimal test prompt)

    Returns a JSON report â never raises, always responds 200.
    """
    import asyncio
    import os

    report: dict = {}

    # ââ 1. Config snapshot âââââââââââââââââââââââââââââââââââââââââââââââ
    try:
        from config import LLMConfig
        backend = LLMConfig.BACKEND
        report["backend"] = backend
        report["model"] = LLMConfig.AICORE_MODEL

        def _mask(val: str) -> str:
            if not val:
                return "â MISSING"
            return val[:6] + "â¦" + val[-4:] if len(val) > 12 else "â SET"

        if backend in ("joule", "aicore"):
            report["credentials"] = {
                "AICORE_API_URL":       _mask(LLMConfig.AICORE_API_URL),
                "AICORE_AUTH_URL":      _mask(LLMConfig.AICORE_AUTH_URL),
                "AICORE_CLIENT_ID":     _mask(LLMConfig.AICORE_CLIENT_ID),
                "AICORE_CLIENT_SECRET": _mask(LLMConfig.AICORE_CLIENT_SECRET),
                "AICORE_RESOURCE_GROUP": LLMConfig.AICORE_RESOURCE_GROUP or "â MISSING",
                "AICORE_DEPLOYMENT_ID": LLMConfig.AICORE_DEPLOYMENT_ID or "(not set â optional)",
            }
        else:
            report["credentials"] = {
                "LLM_API_KEY":  _mask(LLMConfig.OPENAI_API_KEY),
                "LLM_BASE_URL": LLMConfig.OPENAI_BASE_URL or "â MISSING",
            }
    except Exception as e:
        report["config_error"] = str(e)

    # ââ 2. Platform secret mount files âââââââââââââââââââââââââââââââââââ
    secret_mount = "/etc/ums/credentials"
    try:
        if os.path.isdir(secret_mount):
            files = os.listdir(secret_mount)
            report["secret_mount"] = {
                "path":  secret_mount,
                "files": files,
                "aicore_files": [f for f in files if "AICORE" in f.upper() or "aicore" in f.lower()],
            }
        else:
            report["secret_mount"] = {"path": secret_mount, "exists": False}
    except Exception as e:
        report["secret_mount_error"] = str(e)

    # ââ 3. Live LLM ping âââââââââââââââââââââââââââââââââââââââââââââââââ
    try:
        from llm_client import get_openai_client

        llm_client, model = get_openai_client()

        def _ping():
            return llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with the single word: PONG"}],
                max_tokens=10,
                temperature=0,
            )

        resp = await asyncio.to_thread(_ping)
        reply = resp.choices[0].message.content.strip()
        report["llm_ping"] = {
            "status":  "â SUCCESS",
            "reply":   reply,
            "model":   model,
        }
    except Exception as e:
        report["llm_ping"] = {
            "status": "â FAILED",
            "error":  str(e),
        }

    # ââ 4. Overall verdict âââââââââââââââââââââââââââââââââââââââââââââââ
    ping_ok = report.get("llm_ping", {}).get("status", "").startswith("â")
    report["verdict"] = "â LLM is operational" if ping_ok else "â LLM unavailable â will use template fallback"

    return JSONResponse(content=report)

# ---------------------------------------------------------------------------
# A2A message endpoints â catch all paths the platform might call
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
# Unified dispatcher â accepts ANY format / method
# ---------------------------------------------------------------------------

async def _dispatch(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error: body is not valid JSON")

    method = body.get("method", "")
    rpc_id = body.get("id")
    logger.info("Incoming request â method=%r rpc_id=%r path=%s", method, rpc_id, request.url.path)

    # ââ JSON-RPC 2.0 envelope ââââââââââââââââââââââââââââââââââââââââââââ
    if "jsonrpc" in body or "method" in body:
        params = body.get("params") or {}

        # Extract message object â different specs put it in different places
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

    # ââ Direct task body (no JSON-RPC wrapper) âââââââââââââââââââââââââââ
    if "message" in body or "id" in body:
        task_id = body.get("id") or body.get("messageId") or str(uuid.uuid4())
        message = body.get("message", {})
        logger.info("Routing direct task body task_id=%s", task_id)
        return await _run_task(None, task_id, message)

    # ââ Unknown format â treat entire body as text âââââââââââââââââââââââ
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

    logger.info("Task %s â input: %.150s", task_id, user_text)

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
