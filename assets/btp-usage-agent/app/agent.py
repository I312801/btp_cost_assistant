"""
BTP Usage Agent — core logic.

Architecture:
  1. Parse user intent and resolve date range from natural language.
  2. Fetch live data from the BTP Usage Analytics Service (UAS) API.
  3. Pass the structured data + user question to the LLM (Joule/GPT-4o)
     for a dynamic, context-aware natural language response.
  4. Fall back to template responses if the LLM is unavailable.

Confirmed working BTP API parameters:
  - subaccountUsage : fromDate=YYYYMMDD & toDate=YYYYMMDD & subaccountId=UUID
  - monthlyUsage    : fromDate=YYYYMMDD & toDate=YYYYMMDD
  - cloudCreditsDetails : globalAccountId=UUID
"""

import asyncio
import json
import os
import re
import logging
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

from date_utils import resolve_date_range

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(d: date) -> str:
    """Format date as YYYYMMDD — the format the UAS API expects."""
    return d.strftime("%Y%m%d")


def _fmt_iso(yyyymmdd: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD for human-readable display."""
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _strip_record_dates(records: list[dict]) -> list[dict]:
    """
    Remove BTP API billing-period date fields from individual usage records.

    The BTP subaccountUsage API always returns startIsoDate/endIsoDate as the
    full billing month (e.g. 2026-05-01 → 2026-05-31) regardless of the query
    date range. Keeping these confuses the LLM into displaying 'this month'
    even when the user asked for 'this week'. We strip them here and rely on
    the explicit query_period field in the context instead.
    """
    drop_keys = {"startIsoDate", "endIsoDate", "startDate", "endDate"}
    return [{k: v for k, v in r.items() if k not in drop_keys} for r in records]


def _month_range(year: int, month: int):
    """Return (from_date, to_date) strings for a full calendar month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return _fmt(start), _fmt(end)


# ---------------------------------------------------------------------------
# BTP API client
# ---------------------------------------------------------------------------

class BTPClient:
    def __init__(self):
        self.uas_url           = (os.environ.get("BTP_UAS_URL") or "").rstrip("/")
        self.auth_url          = os.environ.get("BTP_AUTH_URL") or ""
        self.client_id         = os.environ.get("BTP_CLIENT_ID") or ""
        self.client_secret     = os.environ.get("BTP_CLIENT_SECRET") or ""
        self.subaccount_id     = os.environ.get("BTP_SUBACCOUNT_ID") or ""
        self.global_account_id = os.environ.get("BTP_GLOBAL_ACCOUNT_ID") or ""
        self._token: str | None = None

    def _check_config(self):
        missing = [k for k, v in {
            "BTP_UAS_URL":       self.uas_url,
            "BTP_AUTH_URL":      self.auth_url,
            "BTP_CLIENT_ID":     self.client_id,
            "BTP_CLIENT_SECRET": self.client_secret,
            "BTP_SUBACCOUNT_ID": self.subaccount_id,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Missing BTP credentials: {', '.join(missing)}")

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        self._check_config()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(self.auth_url, data={
                "grant_type":    "client_credentials",
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            r.raise_for_status()
            self._token = r.json()["access_token"]
            return self._token

    async def _get(self, path: str, params: dict) -> dict | list:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.uas_url}{path}", params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    async def get_subaccount_usage(self, from_date: str, to_date: str) -> list[dict]:
        resp = await self._get("/reports/v1/subaccountUsage", {
            "fromDate":     from_date,
            "toDate":       to_date,
            "subaccountId": self.subaccount_id,
        })
        return resp.get("content", resp) if isinstance(resp, dict) else resp

    async def get_monthly_usage(self, from_date: str, to_date: str) -> list[dict]:
        resp = await self._get("/reports/v1/monthlyUsage", {
            "fromDate":     from_date,
            "toDate":       to_date,
            "subaccountId": self.subaccount_id,
        })
        return resp.get("content", resp) if isinstance(resp, dict) else resp

    async def check_connection(self) -> dict:
        """Quick health probe using the cloudCreditsDetails endpoint."""
        await self._get_token()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{self.uas_url}/reports/v1/cloudCreditsDetails",
                params={"globalAccountId": self.global_account_id},
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            )
        return {
            "ok":          r.status_code == 200,
            "status_code": r.status_code,
            "data":        r.json() if r.status_code == 200 else None,
        }


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    "last 7 days", "last 14 days", "last 30 days",
    "last 3 months", "last 6 months", "last 12 months",
    "last year", "previous year", "this year", "current year",
    "last month", "previous month",
    "this month", "current month",
    "last week", "previous week",
    "this week", "current week",
    "yesterday",
    "today",
]


def _resolve_dates_from_text(text_lower: str) -> tuple[str, str]:
    """Resolve a date expression from user text to (from_date, to_date) in YYYYMMDD."""
    m = re.search(r"last\s+(\d+)\s+(day|week|month)s?", text_lower)
    if m:
        fd, td = resolve_date_range(m.group(0))
        if fd:
            return fd, td

    for pattern in _DATE_PATTERNS:
        if pattern in text_lower:
            fd, td = resolve_date_range(pattern)
            if fd:
                return fd, td

    today = date.today()
    return _month_range(today.year, today.month)


# ---------------------------------------------------------------------------
# LLM response generation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are the BTP Usage Agent — an expert assistant for SAP BTP \
(Business Technology Platform). Your job is to help users understand their BTP \
resource consumption, service usage, entitlements, and costs.

You receive structured JSON context data fetched live from BTP APIs and must turn it \
into a clear, helpful, and concise natural language response.

Guidelines:
- Use markdown formatting (tables, bold, bullet points) where it improves readability.
- Be factual and base your answer strictly on the provided context data.
- If data is empty or missing, explain what that means in plain language.
- Keep responses concise but informative.
- Suggest follow-up questions the user might find useful.

IMPORTANT — Date period:
- The context always contains a "query_period" field with "from" and "to" dates.
- ALWAYS use "query_period.from" and "query_period.to" as the period to display.
- NEVER use date fields from inside individual usage records (those reflect the
  billing month, not the user's requested period).
- Display the period as: <from> → <to>  (e.g. "2026-05-18 → 2026-05-22")
"""


async def _call_llm(user_text: str, context: dict) -> str:
    """Call the configured LLM backend and return a natural language response."""
    from llm_client import get_openai_client

    llm_client, model = get_openai_client()

    user_prompt = (
        f"User question: {user_text}\n\n"
        f"Live context data from BTP APIs:\n"
        f"{json.dumps(context, indent=2, default=str)}\n\n"
        "Please provide a helpful, natural language answer based on this data."
    )

    def _sync_call():
        return llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.2,
        )

    response = await asyncio.to_thread(_sync_call)
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class BTPUsageAgent:
    def __init__(self):
        self.client = BTPClient()

    async def run(self, user_text: str) -> str:
        text_lower = (user_text or "").lower()
        from_date, to_date = _resolve_dates_from_text(text_lower)

        try:
            context = await self._gather_context(text_lower, from_date, to_date)
            return await self._respond(user_text, context)

        except RuntimeError as e:
            return f"⚠️ Configuration error: {e}"
        except httpx.HTTPStatusError as e:
            return _http_error_msg(e)
        except httpx.RequestError as e:
            return f"⚠️ Cannot reach BTP API: {e}"
        except Exception as e:
            logger.exception("Unexpected agent error")
            return f"⚠️ Unexpected error: {e}"

    # ------------------------------------------------------------------
    # Step 1: Gather context data from BTP APIs
    # ------------------------------------------------------------------

    async def _gather_context(self, text_lower: str, from_date: str, to_date: str) -> dict:
        """Fetch the relevant BTP data and return it as a structured context dict."""

        # Connection / health check
        if any(k in text_lower for k in ["connect", "health", "status", "ping", "check"]):
            status = await self.client.check_connection()
            usage = []
            try:
                usage = await self.client.get_subaccount_usage(from_date, to_date)
            except Exception:
                pass
            return {
                "query_type":        "connection_check",
                "connection_status": status,
                "subaccount_id":     self.client.subaccount_id,
                "global_account_id": self.client.global_account_id,
                "query_period": {
                    "from": _fmt_iso(from_date),
                    "to":   _fmt_iso(to_date),
                },
                "usage_sample": _strip_record_dates(usage[:5]),
            }

        # Cost queries — unavailable on trial
        if any(k in text_lower for k in ["cost", "expensive", "spend", "price", "charge", "bill"]):
            return {
                "query_type":   "cost_query",
                "account_type": "trial",
                "note": (
                    "The /reports/v1/monthlyCost endpoint returns HTTP 404 for trial accounts. "
                    "Cost reporting requires an active commercial BTP contract. "
                    "Usage data via subaccountUsage IS available."
                ),
            }

        # Greeting / capability inquiry
        if any(k in text_lower for k in ["help", "hi", "hello", "what can", "capabilities"]):
            return {
                "query_type": "greeting",
                "capabilities": [
                    "Query subaccount service usage for any date range",
                    "Show services being consumed and their metrics",
                    "Check BTP API connection and token health",
                    "Summarise usage trends (last 7 days, last month, etc.)",
                ],
                "example_questions": [
                    "Show my BTP usage",
                    "What services did I use last month?",
                    "Show usage last 7 days",
                    "Check connection",
                ],
            }

        # Default: subaccount usage
        data = await self.client.get_subaccount_usage(from_date, to_date)
        return {
            "query_type":    "subaccount_usage",
            "subaccount_id": self.client.subaccount_id,
            # Explicit query period in ISO format — LLM must use this for display,
            # NOT the startIsoDate/endIsoDate inside individual records (those are
            # monthly billing periods unrelated to the user's requested range).
            "query_period": {
                "from": _fmt_iso(from_date),
                "to":   _fmt_iso(to_date),
            },
            "record_count":  len(data),
            "usage_records": _strip_record_dates(data),
        }

    # ------------------------------------------------------------------
    # Step 2: Generate response via LLM (with template fallback)
    # ------------------------------------------------------------------

    async def _respond(self, user_text: str, context: dict) -> str:
        """Try LLM; return the exception message directly if it fails."""
        try:
            return await _call_llm(user_text, context)
        except Exception as e:
            logger.warning("LLM call failed: %s: %s", type(e).__name__, e)
            return f"⚠️ LLM error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Template fallback (used when LLM is unavailable)
# ---------------------------------------------------------------------------

def _template_fallback(context: dict) -> str:
    """Return a formatted template response from the context dict."""
    qt = context.get("query_type")

    if qt == "connection_check":
        status = context.get("connection_status", {})
        sample = context.get("usage_sample", [])
        lines = [
            "**BTP Connection Status**\n",
            f"• Subaccount ID  : `{context.get('subaccount_id')}`",
            f"• Global Account : `{context.get('global_account_id')}`",
            f"• OAuth token    : ✅ obtained",
            f"• UAS service    : HTTP {status.get('status_code', '?')} "
              + ("✅" if status.get("ok") else "❌"),
            f"• Usage sample   : {len(sample)} record(s) returned",
        ]
        return "\n".join(lines)

    if qt == "cost_query":
        return (
            "⚠️ **Cost data not available for trial accounts.**\n\n"
            "The cost reporting endpoint requires an active commercial BTP contract.\n\n"
            "**What IS available:**\n"
            "• Service usage data via `subaccountUsage` ✅\n\n"
            "Try: **'Show my BTP usage'** or **'What services am I using?'**"
        )

    if qt == "greeting":
        caps = context.get("capabilities", [])
        examples = context.get("example_questions", [])
        lines = ["Hi! I'm the **BTP Usage Agent**.\n", "**I can help you with:**"]
        lines += [f"• {c}" for c in caps]
        lines += ["\n**Try asking:**"]
        lines += [f"• `{e}`" for e in examples]
        return "\n".join(lines)

    # subaccount_usage
    records = context.get("usage_records", [])
    period  = context.get("query_period", {})
    from_dt = period.get("from", "")
    to_dt   = period.get("to", "")

    if not records:
        return (
            f"No usage data found for the period **{from_dt} → {to_dt}**.\n"
            f"Subaccount: `{context.get('subaccount_id')}`"
        )

    lines = [
        f"**BTP Subaccount Usage — {from_dt} → {to_dt}**",
        f"Records: {len(records)}\n",
        "| Service | Plan | Metric | Usage | Unit | Data Center |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in records:
        svc    = item.get("serviceName")  or item.get("serviceId")  or "—"
        plan   = item.get("planName")     or item.get("plan")       or "—"
        metric = item.get("metricName")   or item.get("measureId")  or "—"
        raw_u  = item.get("usage")
        usage  = (f"{raw_u:,.4f}".rstrip("0").rstrip(".") if isinstance(raw_u, float)
                  else str(raw_u) if raw_u is not None else "—")
        unit   = item.get("unitPlural")   or item.get("unitSingular") or "—"
        dc     = item.get("dataCenter")   or "—"
        lines.append(f"| {svc} | {plan} | {metric} | {usage} | {unit} | {dc} |")

    lines.append("\n> Try: 'Show usage last 7 days' · 'Show usage last month' · 'Check connection'")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _http_error_msg(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    if code == 500:
        return (
            "⚠️ BTP UAS API returned HTTP 500.\n"
            "Tip: make sure `fromDate=YYYYMMDD&toDate=YYYYMMDD&subaccountId=UUID` are correct."
        )
    if code == 401:
        return "⚠️ HTTP 401 — token expired or invalid credentials."
    if code == 403:
        return "⚠️ HTTP 403 — insufficient scope for this endpoint."
    if code == 404:
        return "⚠️ HTTP 404 — endpoint not available for this account type."
    return f"⚠️ BTP API error: HTTP {code}"
