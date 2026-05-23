"""
LLM client factory — supports three backends:

  1. aicore (recommended) — SAP AI Core via generative-ai-hub-sdk.
               Credentials loaded explicitly from LLMConfig fields
               (reads AICORE_* env vars baked in .env at build time,
                plus /etc/ums/credentials/ mounted files).
               Model: AICORE_MODEL env var (default: gpt-4o).
               Optional: AICORE_DEPLOYMENT_ID to pin a specific deployment.

  2. joule — Alias for aicore. Uses AICORE_MODEL env var.

  3. openai — Any OpenAI-compatible endpoint (local testing / LiteLLM).
               Uses LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.

Backend is selected by the LLM_BACKEND environment variable (default: aicore).

NOTE: Do NOT use get_proxy_client("gen-ai-hub") auto-detect — it creates a
silent broken client with no exception when credentials are missing/wrong.
Always build GenAIHubProxyClient explicitly from LLMConfig fields.
"""
from __future__ import annotations

import logging
from typing import Any

from config import LLMConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI Core client (shared by joule + aicore backends)
# ---------------------------------------------------------------------------

def _make_aicore_client() -> tuple[Any, str]:
    """
    Build an AICoreOpenAI client using explicit credentials from LLMConfig.

    LLMConfig reads from (in priority order):
      1. Environment variables (AICORE_AUTH_URL, AICORE_CLIENT_ID, etc.)
         — these come from the .env file baked into the Docker image
      2. /etc/ums/credentials/ mounted files
         — injected by platform for production credentials

    NOTE: get_proxy_client("gen-ai-hub") auto-detect is intentionally avoided
    because it creates a silent broken client without raising an exception.
    """
    from gen_ai_hub.proxy.native.openai.clients import OpenAI as AICoreOpenAI

    model = LLMConfig.AICORE_MODEL

    LLMConfig.validate()   # raise early with clear message if fields missing

    # Try multiple known import paths across different SDK versions
    try:
        from gen_ai_hub.proxy.core.proxy_clients import GenAIHubProxyClient
    except ImportError:
        try:
            from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient
        except ImportError:
            from gen_ai_hub.proxy.client import GenAIHubProxyClient

    auth_url = LLMConfig.AICORE_AUTH_URL
    if auth_url and not auth_url.endswith("/oauth/token"):
        auth_url = auth_url.rstrip("/") + "/oauth/token"

    proxy_kwargs: dict[str, Any] = dict(
        base_url=LLMConfig.AICORE_API_URL,
        auth_url=auth_url,
        client_id=LLMConfig.AICORE_CLIENT_ID,
        client_secret=LLMConfig.AICORE_CLIENT_SECRET,
        resource_group=LLMConfig.AICORE_RESOURCE_GROUP,
    )

    # Optional: pin to a specific deployment ID (aicore backend only)
    if LLMConfig.BACKEND == "aicore" and LLMConfig.AICORE_DEPLOYMENT_ID:
        proxy_kwargs["deployment_id"] = LLMConfig.AICORE_DEPLOYMENT_ID

    proxy = GenAIHubProxyClient(**proxy_kwargs)
    client = AICoreOpenAI(proxy_client=proxy)
    logger.info(
        "AI Core client initialised via explicit credentials "
        "(backend=%s, model=%s, resource_group=%s)",
        LLMConfig.BACKEND, model, LLMConfig.AICORE_RESOURCE_GROUP,
    )
    return client, model


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def get_openai_client() -> tuple[Any, str]:
    """
    Return a configured LLM client and the model name to use.

    aicore / joule — AICoreOpenAI via generative-ai-hub-sdk.
                     Credentials loaded explicitly from env vars / mounted files.

    openai         — Standard openai.OpenAI client (LLM_API_KEY / LLM_BASE_URL).
    """
    if LLMConfig.BACKEND in ("joule", "aicore"):
        return _make_aicore_client()

    elif LLMConfig.BACKEND == "openai":
        from openai import OpenAI

        client = OpenAI(
            api_key=LLMConfig.OPENAI_API_KEY,
            base_url=LLMConfig.OPENAI_BASE_URL,
        )
        logger.info("OpenAI-compatible client ready (model=%s)", LLMConfig.AICORE_MODEL)
        return client, LLMConfig.AICORE_MODEL

    else:
        raise ValueError(
            f"Unsupported LLM_BACKEND: '{LLMConfig.BACKEND}'. "
            "Valid values are: 'aicore', 'joule', 'openai'."
        )
