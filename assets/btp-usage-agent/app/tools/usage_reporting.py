"""
BTP Usage Data Management Service -- reporting tools.

Wraps the main endpoints of the UAS Reporting API:
  - /reports/v1/subaccountUsage        (daily / hourly usage per subaccount)
  - /reports/v1/monthlySubaccountUsage (monthly usage per subaccount)
  - /reports/v1/monthlyUsage           (monthly usage for the global account)

Each function returns the parsed JSON response or raises on HTTP errors.
"""
import logging
import requests

from config import BTPConfig
from tools.auth import get_auth_headers

logger = logging.getLogger(__name__)

_BASE = BTPConfig.UAS_BASE_URL.rstrip("/")


def _get(path: str, params: dict) -> dict:
    """Internal helper -- GET request with auth headers and error handling."""
    # Remove None-valued params so we don't send empty query strings
    clean_params = {k: v for k, v in params.items() if v is not None}

    url = f"{_BASE}{path}"
    logger.debug("GET %s  params=%s", url, clean_params)

    response = requests.get(
        url,
        params=clean_params,
        headers={**get_auth_headers(), "Accept": "application/json"},
        timeout=60,
    )

    if response.status_code == 401:
        # Token may have expired mid-session -- retry once with a fresh token
        from tools.auth import get_access_token
        get_access_token(force_refresh=True)
        response = requests.get(
            url,
            params=clean_params,
            headers={**get_auth_headers(), "Accept": "application/json"},
            timeout=60,
        )

    response.raise_for_status()
    return response.json()


# -- Tool functions (called by the LLM via tool-calling) ----------------------

def get_subaccount_usage(
    from_date: str,
    to_date: str,
    subaccount_id: str | None = None,
    period_perspective: str = "DAY",
) -> dict:
    """
    Retrieve daily or hourly service usage for a BTP subaccount.

    Args:
        from_date:          Start date in YYYYMMDD format (e.g. "20260501").
        to_date:            End date   in YYYYMMDD format (e.g. "20260531").
        subaccount_id:      GUID of the subaccount. Defaults to BTP_SUBACCOUNT_ID.
        period_perspective: Granularity -- "DAY" (default) or "HOUR".

    Returns:
        Parsed JSON response from the UAS API.
    """
    return _get(
        "/reports/v1/subaccountUsage",
        {
            "fromDate": from_date,
            "toDate": to_date,
            "subaccountId": subaccount_id or BTPConfig.SUBACCOUNT_ID,
            "periodPerspective": period_perspective,
        },
    )


def get_monthly_subaccount_usage(
    year_month: str,
    subaccount_id: str | None = None,
) -> dict:
    """
    Retrieve aggregated monthly service usage for a BTP subaccount.

    Args:
        year_month:    Month in YYYYMM format (e.g. "202605").
        subaccount_id: GUID of the subaccount. Defaults to BTP_SUBACCOUNT_ID.

    Returns:
        Parsed JSON response from the UAS API.
    """
    return _get(
        "/reports/v1/monthlySubaccountUsage",
        {
            "yearMonth": year_month,
            "subaccountId": subaccount_id or BTPConfig.SUBACCOUNT_ID,
        },
    )


def get_monthly_global_account_usage(
    year_month: str,
    global_account_id: str | None = None,
) -> dict:
    """
    Retrieve aggregated monthly service usage at the global account level.

    Args:
        year_month:        Month in YYYYMM format (e.g. "202605").
        global_account_id: GUID of the global account. Defaults to BTP_GLOBAL_ACCOUNT_ID.

    Returns:
        Parsed JSON response from the UAS API.
    """
    return _get(
        "/reports/v1/monthlyUsage",
        {
            "yearMonth": year_month,
            "globalAccountId": global_account_id or BTPConfig.GLOBAL_ACCOUNT_ID,
        },
    )
