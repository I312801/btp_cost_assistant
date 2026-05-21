"""
Configuration for BTP Usage Agent.
Loads settings from environment variables or a local .env file.

Two LLM backends are supported:

  1. SAP AI Core  (default - OAuth2.0 Client Credentials via XSUAA)
       LLM_BACKEND=aicore
       AICORE_AUTH_URL=https://<tenant>.authentication.<region>.hana.ondemand.com
       AICORE_CLIENT_ID=<clientid>
       AICORE_CLIENT_SECRET=<clientsecret>
       AICORE_API_URL=https://api.ai.<region>.ml.hana.ondemand.com
       AICORE_DEPLOYMENT_ID=<deployment-id>   # optional: leave empty for predefined models
       AICORE_MODEL=<model-name>              # e.g. gpt-4o
       AICORE_RESOURCE_GROUP=default

  2. OpenAI (or any OpenAI-compatible endpoint, e.g. LiteLLM)
       LLM_BACKEND=openai
       LLM_API_KEY=sk-...
       LLM_BASE_URL=https://api.openai.com/v1
       LLM_MODEL=gpt-4o
"""
import os
from dotenv import load_dotenv

load_dotenv()


class BTPConfig:
    """BTP Usage Data Management Service configuration."""

    UAS_BASE_URL: str = os.getenv("BTP_UAS_URL", "https://uas-reporting.cfapps.eu10.hana.ondemand.com")
    AUTH_URL: str = os.getenv("BTP_AUTH_URL", "")
    CLIENT_ID: str = os.getenv("BTP_CLIENT_ID", "")
    CLIENT_SECRET: str = os.getenv("BTP_CLIENT_SECRET", "")
    SUBACCOUNT_ID: str = os.getenv("BTP_SUBACCOUNT_ID", "")
    GLOBAL_ACCOUNT_ID: str = os.getenv("BTP_GLOBAL_ACCOUNT_ID", "")

    @classmethod
    def validate(cls) -> None:
        missing = [k for k, v in {
            "BTP_AUTH_URL": cls.AUTH_URL,
            "BTP_CLIENT_ID": cls.CLIENT_ID,
            "BTP_CLIENT_SECRET": cls.CLIENT_SECRET,
            "BTP_SUBACCOUNT_ID": cls.SUBACCOUNT_ID,
        }.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Copy .env.example to .env and fill in the values."
            )


class LLMConfig:
    """
    LLM backend configuration.

    Set LLM_BACKEND=aicore  (default) to use SAP AI Core via XSUAA OAuth2.0.
    Set LLM_BACKEND=openai  to use OpenAI or any OpenAI-compatible endpoint.
    """

    BACKEND: str = os.getenv("LLM_BACKEND", "aicore").lower()

    # -- SAP AI Core (read by generative-ai-hub-sdk automatically) ------------
    # AICORE_AUTH_URL, AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_API_URL,
    # AICORE_RESOURCE_GROUP, AICORE_DEPLOYMENT_ID are read directly from env
    # by the SDK — no need to redeclare them here.
    AICORE_MODEL: str = os.getenv("AICORE_MODEL", "gpt-4o")

    # -- OpenAI / generic OpenAI-compatible -----------------------------------
    OPENAI_API_KEY: str = os.getenv("LLM_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    @classmethod
    def validate(cls) -> None:
        if cls.BACKEND == "aicore":
            # generative-ai-hub-sdk validates AICORE_* credentials internally.
            # No pre-flight check needed here.
            pass
        else:
            if not cls.OPENAI_API_KEY:
                raise EnvironmentError(
                    "Missing required environment variable: LLM_API_KEY\n"
                    "Set LLM_BACKEND=aicore to use SAP AI Core instead."
                )
