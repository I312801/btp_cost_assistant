"""
BTP Cost & Usage Intelligence Agent — A2A HTTP Server entry point.

Exposes the BTPUsageAgent via an A2A-compatible REST API:
  GET  /.well-known/agent.json  →  Agent Card (discovery metadata)
  POST /                        →  Send a task (single-turn or multi-turn)
  GET  /health                  →  Health probe

Usage:
    uvicorn server:app --host 0.0.0.0 --port 5001
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="BTP Cost & Usage Intelligence Agent", version="1.0.0")

# Lazy-initialised agent singleton (avoids startup failure when env vars are missing)
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from agent import BTPUsageAgent  # noqa: PLC0415
        _agent = BTPUsageAgent()
    return _agent


# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD: dict[str, Any] = {
    "name": "BTP Cost & Usage Intelligence Agent",
    "description": (
        "Answers natural-language questions about SAP BTP account usage and cost "
        "by querying the BTP Usage Data Management Service APIs."
    ),
    "version": "1.0.0",
    "url": "",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "authentication": {"schemes": ["Bearer"]},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "btp-usage-query",
            "name": "BTP Usage Query",
            "description": (
                "Query SAP BTP subaccount or global account usage and cost data "
                "for a given time period using natural language."
            ),
            "tags": ["btp", "usage", "cost", "cloud"],
            "examples": [
                "Show me the subaccount usage this week",
                "What services did we consume last month?",
                "Give me daily usage from May 1 to June 1 2026",
                "Show the monthly global account cost for May 2026",
            ],
        }
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    """Return the A2A Agent Card for discovery."""
    return JSONResponse(content=AGENT_CARD)


# ── Health probe ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── A2A Task endpoint ─────────────────────────────────────────────────────────

class TaskMessage(BaseModel):
    role: str
    parts: list[dict]


class SendTaskRequest(BaseModel):
    id: str | None = None
    message: TaskMessage
    sessionId: str | None = None


@app.post("/")
async def send_task(request: Request):
    """
    A2A-compatible task endpoint.

    Accepts:
        {
          "id": "<task-id>",
          "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "<user question>"}]
          },
          "sessionId": "<optional-session-id>"
        }

    Returns an A2A Task object with the agent's answer.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract user text from A2A message parts
    message = body.get("message", {})
    parts = message.get("parts", [])
    user_text = " ".join(
        p.get("text", "") for p in parts if p.get("type") == "text"
    ).strip()

    if not user_text:
        raise HTTPException(status_code=400, detail="No text content found in message parts")

    task_id = body.get("id") or str(uuid.uuid4())

    try:
        agent = _get_agent()
        answer = agent.chat(user_text)
    except EnvironmentError as exc:
        logger.error("Agent configuration error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Error during agent.chat()")
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse(
        content={
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "parts": [{"type": "text", "text": answer}],
                    "index": 0,
                }
            ],
        }
    )
