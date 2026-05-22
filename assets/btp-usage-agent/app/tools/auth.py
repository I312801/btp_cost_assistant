"""
OAuth2.0 Client Credentials token management for BTP Usage Data Management Service.
Automatically refreshes the token when it expires.
"""
import time
import logging
import requests

from config import BTPConfig

logger = logging.getLogger(__name__)

_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token(force_refresh: bool = False) -> str:
    """
    Retrieve a valid OAuth2.0 access token using Client Credentials flow.

    Tokens are cached in memory and automatically refreshed 30 seconds before
    expiry to avoid clock-skew issues.

    Args:
        force_refresh: Skip the cache and obtain a fresh token.

    Returns:
        A valid Bearer access token string.

    Raises:
        requests.HTTPError: If the token endpoint returns an error.
    """
    now = time.time()
    if not force_refresh and _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]  # type: ignore[return-value]

    # BTP_AUTH_URL is the full token endpoint URL (already includes /oauth/token)
    token_url = BTPConfig.AUTH_URL
    logger.debug("Fetching new OAuth2.0 token from %s", token_url)

    response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": BTPConfig.CLIENT_ID,
            "client_secret": BTPConfig.CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    response.raise_for_status()

    token_data = response.json()
    access_token: str = token_data["access_token"]
    expires_in: int = token_data.get("expires_in", 3600)

    # Cache with 30-second safety margin
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in - 30

    logger.debug("Token obtained, expires in %d seconds", expires_in)
    return access_token


def get_auth_headers() -> dict:
    """Return Authorization headers ready for HTTP requests."""
    return {"Authorization": f"Bearer {get_access_token()}"}
