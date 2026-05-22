"""
LLM client factory — supports three backends:

  1. joule / aicore (default: joule) — SAP AI Core via generative-ai-hub-sdk.
               Uses AICoreV2Client + AICoreOpenAI native client for full
               OpenAI-compatible tool calling and multi-turn conversations.
               Reads from config: AICORE_API_URL, AICORE_AUTH_URL,
               AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_RESOURCE_GROUP.

  2. openai  — Any OpenAI-compatible endpoint (local testing / LiteLLM).
               Uses LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.

Backend is selected by the LLM_BACKEND environment variable (default: joule).
"""
from __future__ import annotations

import logging
from typing import Any

from config import LLMConfig

logger = logging.getLogger(__name__)


def _make_aicore_client() -> tuple[Any, str]:
    """
    Build an AICoreOpenAI client by explicitly passing credentials from config.
    gen_ai_hub v4.x requires explicit initialisation of AICoreV2Client.
    AICORE_AUTH_URL must be the full token endpoint (including /oauth/token).
    """
    from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient
    from gen_ai_hub.proxy.native.openai.clients import OpenAI as AICoreOpenAI

    model = LLMConfig.JOULE_MODEL if LLMConfig.BACKEND == "joule" else LLMConfig.AICORE_MODEL

    # Ensure auth_url ends with /oauth/token
    auth_url = LLMConfig.AICORE_AUTH_URL
    if not auth_url.endswith("/oauth/token"):
        auth_url = auth_url.rstrip("/") + "/oauth/token"

    proxy = GenAIHubProxyClient(
        base_url=LLMConfig.AICORE_API_URL,
        auth_url=auth_url,
        client_id=LLMConfig.AICORE_CLIENT_ID,
        client_secret=LLMConfig.AICORE_CLIENT_SECRET,
        resource_group=LLMConfig.AICORE_RESOURCE_GROUP,
    )
    client = AICoreOpenAI(proxy_client=proxy)
    logger.debug("AI Core (Joule) client ready (backend: %s, model: %s)", LLMConfig.BACKEND, model)
    return client, model


def get_openai_client() -> tuple[Any, str]:
    """
    Return a configured LLM client and the model name to use.

    joule / aicore → AICoreOpenAI backed by AICoreV2Client.
                     Fully OpenAI-compatible; supports multi-turn and tools.

    openai         → Standard openai.OpenAI with LLM_API_KEY / LLM_BASE_URL.
    """
    if LLMConfig.BACKEND in ("joule", "aicore"):
        return _make_aicore_client()

    elif LLMConfig.BACKEND == "openai":
        from openai import OpenAI

        client = OpenAI(
            api_key=LLMConfig.OPENAI_API_KEY,
            base_url=LLMConfig.OPENAI_BASE_URL,
        )
        logger.debug("OpenAI-compatible client ready (model: %s)", LLMConfig.OPENAI_MODEL)
        return client, LLMConfig.OPENAI_MODEL

    else:
        raise ValueError(
            f"Unsupported LLM_BACKEND: '{LLMConfig.BACKEND}'. "
            "Valid values are: 'joule', 'aicore', 'openai'."
        )
