"""
BTP Usage Agent — core logic.

Correct API parameters (confirmed by live test):
  - subaccountUsage : fromDate=YYYYMMDD & toDate=YYYYMMDD & subaccountId=UUID  → 200 ✅
  - monthlyUsage    : fromDate=YYYYMMDD & toDate=YYYYMMDD                      → 200 (empty for trial)
  - monthlyCost     : not available for trial accounts (404)
"""

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


def _month_range(year: int, month: int):
    """Return (from_date, to_date) strings for a full calendar month."""
    start = date(year, month, 1)
    # last day: first day of next month minus 1
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
        self.uas_url       = (os.environ.get("BTP_UAS_URL") or "").rstrip("/")
        self.auth_url      = os.environ.get("BTP_AUTH_URL") or ""
        self.client_id     = os.environ.get("BTP_CLIENT_ID") or ""
        self.client_secret = os.environ.get("BTP_CLIENT_SECRET") or ""
        self.subaccount_id = os.environ.get("BTP_SUBACCOUNT_ID") or ""
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

    # ── Public methods ──────────────────────────────────────────────────

    async def get_subaccount_usage(self, from_date: str, to_date: str) -> list[dict]:
        """
        Confirmed working: fromDate + toDate + subaccountId.
        Returns content[] list.
        """
        resp = await self._get("/reports/v1/subaccountUsage", {
            "fromDate":     from_date,
            "toDate":       to_date,
            "subaccountId": self.subaccount_id,
        })
        return resp.get("content", resp) if isinstance(resp, dict) else resp

    async def get_monthly_usage(self, from_date: str, to_date: str) -> list[dict]:
        """
        Global account-level usage. Returns empty for trial accounts but endpoint is alive.
        """
        resp = await self._get("/reports/v1/monthlyUsage", {
            "fromDate":     from_date,
            "toDate":       to_date,
            "subaccountId": self.subaccount_id,
        })
        return resp.get("content", resp) if isinstance(resp, dict) else resp

    async def check_connection(self) -> dict:
        """Quick health probe using the most reliable endpoint."""
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

# Ordered from most-specific to least-specific so "last week" is matched
# before "week" alone, and "last month" before "month" alone.
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
    """
    Scan the lower-cased user message for a date expression and resolve it
    to (from_date, to_date) in YYYYMMDD format.

    Priority:
      1. Dynamic "last N days/weeks/months" pattern via regex.
      2. Fixed phrase match from _DATE_PATTERNS list.
      3. Default: current calendar month (unchanged prior behaviour).
    """
    # 1. "last N days / weeks / months"
    m = re.search(r"last\s+(\d+)\s+(day|week|month)s?", text_lower)
    if m:
        fd, td = resolve_date_range(m.group(0))
        if fd:
            logger.debug("Date resolved via regex '%s': %s → %s", m.group(0), fd, td)
            return fd, td

    # 2. Fixed-phrase lookup
    for pattern in _DATE_PATTERNS:
        if pattern in text_lower:
            fd, td = resolve_date_range(pattern)
            if fd:
                logger.debug("Date resolved via pattern '%s': %s → %s", pattern, fd, td)
                return fd, td

    # 3. Default: current month
    today = date.today()
    fd, td = _month_range(today.year, today.month)
    logger.debug("No date expression found — defaulting to current month: %s → %s", fd, td)
    return fd, td


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
            # ── connection / health ───────────────────────────────────
            if any(k in text_lower for k in ["connect", "health", "status", "ping", "check"]):
                return await self._answer_connection(from_date, to_date)

            # ── cost (not available on trial — explain clearly) ───────
            if any(k in text_lower for k in ["cost", "expensive", "spend", "price", "charge", "bill"]):
                return await self._answer_costs_unavailable()

            # ── subaccount or general usage ───────────────────────────
            if any(k in text_lower for k in [
                "subaccount", "sub-account", "usage", "consumption",
                "use", "utiliz", "utilis", "service", "what"
            ]):
                return await self._answer_subaccount_usage(from_date, to_date)

            # ── greeting ──────────────────────────────────────────────
            if any(k in text_lower for k in ["help", "hi", "hello", "what can", "capabilities"]):
                return self._greeting()

            # ── default: subaccount usage summary ─────────────────────
            return await self._answer_subaccount_usage(from_date, to_date)

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

    async def _answer_subaccount_usage(self, from_date: str, to_date: str) -> str:
        data = await self.client.get_subaccount_usage(from_date, to_date)
        if not data:
            return (
                f"No usage data found for the period {from_date} → {to_date}.\n"
                f"Subaccount: `{self.client.subaccount_id}`"
            )

        sa_name  = data[0].get("subaccountName") or self.client.subaccount_id
        start    = data[0].get("startIsoDate") or from_date
        end      = data[0].get("endIsoDate")   or to_date

        lines = [
            f"**BTP Subaccount Usage — {sa_name}**",
            f"Period: {start} → {end}  |  Records: {len(data)}\n",
            "| Service Name | Plan | Metric | Usage | Unit | Data Center |",
            "| --- | --- | --- | --- | --- | --- |",
        ]

        for item in data:
            svc    = item.get("serviceName")  or item.get("serviceId")  or "—"
            plan   = item.get("planName")     or item.get("plan")       or "—"
            metric = item.get("metricName")   or item.get("measureId")  or "—"
            raw_u  = item.get("usage")
            usage  = (f"{raw_u:,.4f}".rstrip("0").rstrip(".") if isinstance(raw_u, float)
                      else str(raw_u) if raw_u is not None else "—")
            unit   = item.get("unitPlural")   or item.get("unitSingular") or "—"
            dc     = item.get("dataCenter")   or "—"
            lines.append(f"| {svc} | {plan} | {metric} | {usage} | {unit} | {dc} |")

        lines.append(
            f"\n> Ask: 'Show usage last 7 days' · 'Show usage this month' · 'Check connection'"
        )
        return "\n".join(lines)

    async def _answer_connection(self, from_date: str, to_date: str) -> str:
        status = await self.client.check_connection()
        contracts = (status.get("data") or {}).get("contracts", [])
        lines = [
            "**BTP Connection Status**\n",
            f"• Subaccount ID  : `{self.client.subaccount_id}`",
            f"• Global Account : `{self.client.global_account_id}`",
            f"• OAuth token    : ✅ obtained",
            f"• UAS service    : HTTP {status['status_code']} "
              + ("✅" if status["ok"] else "❌"),
            f"• Contracts      : {len(contracts)} (trial = 0 is normal)",
            "",
            "**Confirmed working endpoint:**",
            f"  `GET /reports/v1/subaccountUsage`",
            f"  params: `fromDate={from_date}&toDate={to_date}`",
            f"         `subaccountId={self.client.subaccount_id}`",
        ]

        # Live probe of the working endpoint
        try:
            data = await self.client.get_subaccount_usage(from_date, to_date)
            lines.append(f"\n✅ subaccountUsage live test: {len(data)} record(s) returned")
        except Exception as e:
            lines.append(f"\n❌ subaccountUsage live test failed: {e}")

        return "\n".join(lines)

    @staticmethod
    async def _answer_costs_unavailable() -> str:
        return (
            "⚠️ **Cost data not available for this account.**\n\n"
            "The `/reports/v1/monthlyCost` endpoint returns HTTP 404 for trial accounts — "
            "cost reporting requires an active commercial BTP contract.\n\n"
            "**What IS available:**\n"
            "• Service usage data via `subaccountUsage` ✅\n\n"
            "Try: **'Show my BTP usage'** or **'What services am I using?'**"
        )

    @staticmethod
    def _greeting() -> str:
        return (
            "Hi! I'm the **BTP Usage Agent**.\n\n"
            "I can query your SAP BTP subaccount usage via the Usage & Cost Management API.\n\n"
            "**Questions you can ask:**\n"
            "• `Show my BTP usage`              → service consumption this month\n"
            "• `What services am I using?`      → same, grouped by service\n"
            "• `Show subaccount usage`          → detailed subaccount breakdown\n"
            "• `Show usage last 7 days`         → shorter date range\n"
            "• `Check connection`               → verify API connectivity + live test\n\n"
            "*(Cost breakdown not available on trial accounts)*"
        )


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _http_error_msg(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    if code == 500:
        return (
            "⚠️ BTP UAS API returned HTTP 500.\n"
            "Tip: make sure you are passing `fromDate=YYYYMMDD&toDate=YYYYMMDD&subaccountId=UUID`."
        )
    if code == 401:
        return "⚠️ HTTP 401 — token expired, please retry."
    if code == 403:
        return "⚠️ HTTP 403 — insufficient scope for this endpoint."
    if code == 404:
        return "⚠️ HTTP 404 — endpoint not available for this account type."
    return f"⚠️ BTP API error: HTTP {code}"
