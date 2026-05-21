"""
LLM client factory - supports two backends:

  1. aicore  (default, production) - SAP AI Core via generative-ai-hub-sdk.
       The SDK handles XSUAA OAuth2.0 authentication automatically using:
       AICORE_AUTH_URL, AICORE_CLIENT_ID, AICORE_CLIENT_SECRET,
       AICORE_API_URL, AICORE_RESOURCE_GROUP, AICORE_DEPLOYMENT_ID

  2. openai  (local testing only) - Any OpenAI-compatible endpoint.
       Intended for local testing with a LiteLLM proxy.
       Uses LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.

Backend is selected by the LLM_BACKEND environment variable (default: aicore).
"""
from __future__ import annotations

import logging
from typing import Any

from gen_ai_hub.proxy.native.openai.clients import OpenAI as AICoreOpenAI
from openai import OpenAI

from config import LLMConfig

logger = logging.getLogger(__name__)


def get_openai_client() -> tuple[Any, str]:
    """
    Return a configured LLM client and the model name to use.

    aicore  → AICoreOpenAI() from generative-ai-hub-sdk.
              Reads AICORE_* env vars and manages XSUAA auth automatically.

    openai  → Standard openai.OpenAI client with LLM_API_KEY / LLM_BASE_URL.
              Compatible with LiteLLM and any OpenAI-compatible proxy.
    """
    if LLMConfig.BACKEND == "aicore":
        client = AICoreOpenAI()
        logger.debug("AI Core client ready (model: %s)", LLMConfig.AICORE_MODEL)
        return client, LLMConfig.AICORE_MODEL

    elif LLMConfig.BACKEND == "openai":
        client = OpenAI(
            api_key=LLMConfig.OPENAI_API_KEY,
            base_url=LLMConfig.OPENAI_BASE_URL,
        )
        logger.debug("OpenAI-compatible client ready (base_url: %s, model: %s)",
                     LLMConfig.OPENAI_BASE_URL, LLMConfig.OPENAI_MODEL)
        return client, LLMConfig.OPENAI_MODEL

    else:
        raise ValueError(
            f"Unsupported LLM_BACKEND: '{LLMConfig.BACKEND}'. "
            "Valid values are: 'aicore', 'openai'."
        )
