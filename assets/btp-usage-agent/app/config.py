"""
Configuration for BTP Usage Agent.
Loads settings from environment variables or a local .env file.

Three LLM backends are supported:

  1. Joule / SAP AI Core Orchestration  (default)
       LLM_BACKEND=joule
       Uses the SAP AI Core Orchestration Service — the same engine that
       powers SAP Joule. Credentials are shared with the aicore backend.
       AICORE_AUTH_URL, AICORE_CLIENT_ID, AICORE_CLIENT_SECRET,
       AICORE_API_URL, AICORE_RESOURCE_GROUP are read by the SDK automatically.
       JOULE_MODEL=gpt-4o   (or any model deployed in your AI Core instance)

  2. SAP AI Core native OpenAI-compatible client
       LLM_BACKEND=aicore
       AICORE_AUTH_URL, AICORE_CLIENT_ID, AICORE_CLIENT_SECRET,
       AICORE_API_URL, AICORE_DEPLOYMENT_ID, AICORE_MODEL, AICORE_RESOURCE_GROUP

  3. OpenAI (or any OpenAI-compatible endpoint, e.g. LiteLLM)
       LLM_BACKEND=openai
       LLM_API_KEY=sk-...
       LLM_BASE_URL=https://api.openai.com/v1
       LLM_MODEL=gpt-4o
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Path where the platform mounts the cred-customer-agent secret as files
_SECRET_MOUNT = "/etc/ums/credentials"


def _secret(key: str, default: str = "") -> str:
    """Read a value from env var, falling back to the mounted secret file."""
    val = os.getenv(key)
    if val:
        return val
    path = os.path.join(_SECRET_MOUNT, key)
    if os.path.isfile(path):
        with open(path) as f:
            return f.read().strip()
    return default


class BTPConfig:
    """BTP Usage Data Management Service configuration."""

    UAS_BASE_URL: str = _secret("BTP_UAS_URL", "https://uas-reporting.cfapps.eu10.hana.ondemand.com")
    AUTH_URL: str = _secret("BTP_AUTH_URL")
    CLIENT_ID: str = _secret("BTP_CLIENT_ID")
    CLIENT_SECRET: str = _secret("BTP_CLIENT_SECRET")
    SUBACCOUNT_ID: str = _secret("BTP_SUBACCOUNT_ID")
    GLOBAL_ACCOUNT_ID: str = _secret("BTP_GLOBAL_ACCOUNT_ID")

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

    Set LLM_BACKEND=joule   (default) to use the SAP AI Core Orchestration
                              Service — the same engine that powers SAP Joule.
    Set LLM_BACKEND=aicore  to use the SAP AI Core native OpenAI-compatible client.
    Set LLM_BACKEND=openai  to use OpenAI or any OpenAI-compatible endpoint.
    """

    BACKEND: str = os.getenv("LLM_BACKEND", "joule").lower()

    # -- SAP AI Core Orchestration / Joule ------------------------------------
    # AICORE_AUTH_URL, AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_API_URL,
    # AICORE_RESOURCE_GROUP are read directly from env by the SDK.
    JOULE_MODEL: str = os.getenv("JOULE_MODEL", "gpt-4o")

    # -- SAP AI Core shared credentials (used by both joule and aicore) -------
    AICORE_API_URL: str = os.getenv("AICORE_API_URL", "")
    AICORE_AUTH_URL: str = os.getenv("AICORE_AUTH_URL", "")
    AICORE_CLIENT_ID: str = os.getenv("AICORE_CLIENT_ID", "")
    AICORE_CLIENT_SECRET: str = os.getenv("AICORE_CLIENT_SECRET", "")
    AICORE_RESOURCE_GROUP: str = os.getenv("AICORE_RESOURCE_GROUP", "default")

    # -- SAP AI Core native client --------------------------------------------
    AICORE_DEPLOYMENT_ID: str = os.getenv("AICORE_DEPLOYMENT_ID", "")
    AICORE_MODEL: str = os.getenv("AICORE_MODEL", "gpt-4o")

    # -- OpenAI / generic OpenAI-compatible -----------------------------------
    OPENAI_API_KEY: str = os.getenv("LLM_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    @classmethod
    def validate(cls) -> None:
        if cls.BACKEND in {"joule", "aicore"}:
            # generative-ai-hub-sdk validates AICORE_* credentials internally.
            pass
        elif cls.BACKEND == "openai":
            if not cls.OPENAI_API_KEY:
                raise EnvironmentError(
                    "Missing required environment variable: LLM_API_KEY\n"
                    "Set LLM_BACKEND=joule to use SAP Joule / AI Core Orchestration instead."
                )
        else:
            raise ValueError(
                f"Unsupported LLM_BACKEND: '{cls.BACKEND}'. "
                "Valid values are: 'joule', 'aicore', 'openai'."
            )
