"""
BTP Cost & Usage Intelligence Agent.

Uses an LLM with OpenAI-compatible tool-calling to answer natural language
questions about SAP BTP account usage and cost by calling the BTP Usage Data
Management Service APIs.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from config import BTPConfig, LLMConfig
from llm_client import get_openai_client
from tools import (
    get_subaccount_usage,
    get_monthly_subaccount_usage,
    get_monthly_global_account_usage,
)
from date_utils import resolve_date_range, resolve_year_month, fmt, today

logger = logging.getLogger(__name__)

# -- Tool schemas (passed to the LLM) -----------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_subaccount_usage",
            "description": (
                "Retrieve daily or hourly service usage and cost metrics for a "
                "BTP subaccount over a date range. Use this for questions like "
                "'show me usage this week', 'what did we consume last month', "
                "'daily usage between date A and date B', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "Start date in YYYYMMDD format, e.g. '20260501'.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "End date in YYYYMMDD format, e.g. '20260531'.",
                    },
                    "subaccount_id": {
                        "type": "string",
                        "description": (
                            f"Subaccount GUID. Defaults to the configured subaccount "
                            f"({BTPConfig.SUBACCOUNT_ID}). Only override if a different "
                            "subaccount is mentioned."
                        ),
                    },
                    "period_perspective": {
                        "type": "string",
                        "enum": ["DAY", "HOUR"],
                        "description": "Granularity of the report. Defaults to 'DAY'.",
                    },
                },
                "required": ["from_date", "to_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_subaccount_usage",
            "description": (
                "Retrieve aggregated monthly service usage and cost for a BTP "
                "subaccount. Use for questions like 'monthly usage for May 2026', "
                "'what was our cost last month', 'show me this month's bill'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year_month": {
                        "type": "string",
                        "description": "Month in YYYYMM format, e.g. '202605'.",
                    },
                    "subaccount_id": {
                        "type": "string",
                        "description": (
                            f"Subaccount GUID. Defaults to the configured subaccount "
                            f"({BTPConfig.SUBACCOUNT_ID})."
                        ),
                    },
                },
                "required": ["year_month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_global_account_usage",
            "description": (
                "Retrieve aggregated monthly service usage and cost at the global "
                "account level across ALL subaccounts. Use for questions about the "
                "entire BTP account, global spending, or cross-subaccount cost summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year_month": {
                        "type": "string",
                        "description": "Month in YYYYMM format, e.g. '202605'.",
                    },
                    "global_account_id": {
                        "type": "string",
                        "description": (
                            f"Global account GUID. Defaults to the configured account "
                            f"({BTPConfig.GLOBAL_ACCOUNT_ID})."
                        ),
                    },
                },
                "required": ["year_month"],
            },
        },
    },
]

# -- Tool dispatcher ----------------------------------------------------------

_TOOL_MAP: dict[str, Any] = {
    "get_subaccount_usage": get_subaccount_usage,
    "get_monthly_subaccount_usage": get_monthly_subaccount_usage,
    "get_monthly_global_account_usage": get_monthly_global_account_usage,
}


def _call_tool(name: str, arguments: str) -> str:
    """Execute a tool call and return its result as a JSON string."""
    func = _TOOL_MAP.get(name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {name}"})

    args: dict = json.loads(arguments)
    logger.debug("Calling tool %s with args %s", name, args)

    try:
        result = func(**args)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.exception("Tool %s raised an error", name)
        return json.dumps({"error": str(exc)})


# -- System prompt ------------------------------------------------------------

def _system_prompt() -> str:
    t = today()
    return f"""You are an intelligent SAP BTP Cost & Usage Assistant.

Today's date is {t.isoformat()} (YYYYMMDD: {fmt(t)}).

Your capabilities:
- Retrieve daily/hourly subaccount usage (get_subaccount_usage)
- Retrieve monthly subaccount usage    (get_monthly_subaccount_usage)
- Retrieve monthly global account cost  (get_monthly_global_account_usage)

Default subaccount ID : {BTPConfig.SUBACCOUNT_ID}
Default global account: {BTPConfig.GLOBAL_ACCOUNT_ID}

Guidelines:
1. Convert relative date expressions ("this week", "last month", "yesterday",
   "last 7 days", etc.) to absolute YYYYMMDD or YYYYMM dates before calling tools.
2. When the user asks about a period that spans a whole month, prefer
   get_monthly_subaccount_usage for cleaner aggregated numbers.
3. For multi-day ranges within a month or cross-month ranges, use
   get_subaccount_usage with DAY perspective.
4. Always present results in a clear, human-readable format. Highlight the
   most important metrics: services consumed, quantities, costs (if available),
   and the time period covered.
5. If the API returns an error, explain it in plain English and suggest next steps.
6. Never expose raw credentials or internal IDs beyond what is needed to answer.
"""


# -- Agent class --------------------------------------------------------------

class BTPUsageAgent:
    """
    Conversational agent that uses LLM tool-calling to answer BTP usage questions.
    Maintains a rolling conversation history for multi-turn interactions.

    Supports two LLM backends (set LLM_BACKEND in .env):
      - openai  : static API key, any OpenAI-compatible endpoint (including LiteLLM)
      - aicore  : SAP AI Core via XSUAA OAuth2.0 (token auto-refreshed per call)
    """

    def __init__(self) -> None:
        BTPConfig.validate()
        LLMConfig.validate()
        self._history: list[dict] = []
        self._reset_history()

    def _reset_history(self) -> None:
        self._history = [{"role": "system", "content": _system_prompt()}]

    def chat(self, user_message: str) -> str:
        """
        Process a user message and return the assistant's response.
        Handles multi-step tool calls automatically.
        """
        self._history.append({"role": "user", "content": user_message})

        for _ in range(10):  # safety limit
            client, model = get_openai_client()

            response = client.chat.completions.create(
                model=model,
                messages=self._history,
                tools=TOOLS,
                tool_choice="auto",
            )

            message = response.choices[0].message
            self._history.append(message.model_dump(exclude_unset=True))

            if not message.tool_calls:
                return message.content or ""

            for tc in message.tool_calls:
                tool_result = _call_tool(tc.function.name, tc.function.arguments)
                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )

        return "I reached the maximum number of reasoning steps. Please try rephrasing your question."

    def reset(self) -> None:
        """Clear conversation history (start a new session)."""
        self._reset_history()
