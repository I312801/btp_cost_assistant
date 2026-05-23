"""
Configuration for BTP Usage Agent.
Loads settings from environment variables or a local .env file.

Three LLM backends are supported:

  1. SAP AI Core (default, recommended)
       LLM_BACKEND=aicore
       Credentials: AICORE_SERVICE_KEY (JSON) or individual AICORE_* fields.

  2. joule — Alias for aicore, same credentials.
       LLM_BACKEND=joule

  3. OpenAI (or any OpenAI-compatible endpoint, e.g. LiteLLM)
       LLM_BACKEND=openai
       LLM_API_KEY=sk-...
       LLM_BASE_URL=https://api.openai.com/v1

  Model selection (all backends):
       AICORE_MODEL=gpt-4o   — controls the model for aicore/joule backends.
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

    UAS_BASE_URL: str  = _secret("BTP_UAS_URL", "https://uas-reporting.cfapps.eu10.hana.ondemand.com")
    AUTH_URL: str      = _secret("BTP_AUTH_URL")
    CLIENT_ID: str     = _secret("BTP_CLIENT_ID")
    CLIENT_SECRET: str = _secret("BTP_CLIENT_SECRET")
    SUBACCOUNT_ID: str = _secret("BTP_SUBACCOUNT_ID")
    GLOBAL_ACCOUNT_ID: str = _secret("BTP_GLOBAL_ACCOUNT_ID")

    @classmethod
    def validate(cls) -> None:
        missing = [k for k, v in {
            "BTP_AUTH_URL":      cls.AUTH_URL,
            "BTP_CLIENT_ID":     cls.CLIENT_ID,
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

    LLM_BACKEND  — selects the backend: aicore (default), joule, openai.
    AI_MODEL     — model name used by ALL backends (default: gpt-4o).

    AICORE credentials are read from environment variables first, then from
    platform-mounted secret files at /etc/ums/credentials/.
    """

    BACKEND: str  = os.getenv("LLM_BACKEND", "aicore").lower()

    # Model name used across all backends
    AICORE_MODEL: str = os.getenv("AICORE_MODEL", "gpt-4o")

    # -- SAP AI Core full service key (Option A — takes priority if set) ------
    AICORE_SERVICE_KEY: str = os.getenv("AICORE_SERVICE_KEY", "")

    # -- SAP AI Core individual credentials (Option B) ------------------------
    # Uses _secret() — reads from env vars AND /etc/ums/credentials/ files.
    AICORE_API_URL: str        = _secret("AICORE_API_URL")
    AICORE_AUTH_URL: str       = _secret("AICORE_AUTH_URL")
    AICORE_CLIENT_ID: str      = _secret("AICORE_CLIENT_ID")
    AICORE_CLIENT_SECRET: str  = _secret("AICORE_CLIENT_SECRET")
    AICORE_RESOURCE_GROUP: str = _secret("AICORE_RESOURCE_GROUP") or "default"
    AICORE_DEPLOYMENT_ID: str  = _secret("AICORE_DEPLOYMENT_ID")

    # -- OpenAI / generic OpenAI-compatible -----------------------------------
    OPENAI_API_KEY: str  = os.getenv("LLM_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

    @classmethod
    def validate(cls) -> None:
        if cls.BACKEND in {"joule", "aicore"}:
            if cls.AICORE_SERVICE_KEY:
                return  # gen_ai_hub auto-detects from SERVICE_KEY
            missing = [k for k, v in {
                "AICORE_API_URL":       cls.AICORE_API_URL,
                "AICORE_AUTH_URL":      cls.AICORE_AUTH_URL,
                "AICORE_CLIENT_ID":     cls.AICORE_CLIENT_ID,
                "AICORE_CLIENT_SECRET": cls.AICORE_CLIENT_SECRET,
            }.items() if not v]
            if missing:
                raise EnvironmentError(
                    f"AI Core backend requires either AICORE_SERVICE_KEY (full JSON) "
                    f"or these individual fields: {', '.join(missing)}\n"
                    "Set them as env vars, in .env, or in /etc/ums/credentials/."
                )
        elif cls.BACKEND == "openai":
            if not cls.OPENAI_API_KEY:
                raise EnvironmentError(
                    "Missing required environment variable: LLM_API_KEY\n"
                    "Set LLM_BACKEND=aicore to use SAP AI Core instead."
                )
        else:
            raise ValueError(
                f"Unsupported LLM_BACKEND: '{cls.BACKEND}'. "
                "Valid values are: 'aicore', 'joule', 'openai'."
            )
