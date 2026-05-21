# BTPCostDetect -- BTP Cost & Usage Intelligence Agent

A conversational AI agent that answers natural-language questions about SAP BTP
account usage and cost by querying the BTP Usage Data Management Service APIs.

---

## Project Structure

```
solution-root/
+-- solution.yaml                        # Solution manifest (do not edit manually)
|
+-- assets/
    +-- btp-usage-agent/                 # The ONE and ONLY source for this agent
        +-- asset.yaml                   # Platform asset descriptor (Kubernetes config)
        +-- Dockerfile                   # Container build instructions
        +-- requirements.txt             # Production Python dependencies
        +-- app/                         # ALL application source code lives here
            +-- .env                     # Local credentials (never commit this)
            +-- .env.example             # Credentials template (safe to commit)
            +-- agent.py                 # Core agent logic & LLM tool-calling loop
            +-- config.py                # Environment variable configuration
            +-- date_utils.py            # Natural-language date parsing
            +-- llm_client.py            # LLM client factory (AI Core / OpenAI)
            +-- main.py                  # Entry point (--cli for interactive, default: server)
            +-- server.py                # A2A HTTP server (deployed entry point)
            +-- tools/                   # BTP API tool implementations
                +-- __init__.py
                +-- auth.py
                +-- usage_reporting.py
```

---

## Golden Rule: Single Source of Truth

> **All code changes MUST be made inside `assets/btp-usage-agent/app/`.**
>
> Do NOT create a parallel folder (e.g. `btp-usage-agent/` at the root) as a
> "development copy". There is no separate dev vs. deploy codebase -- the same
> `app/` folder is used for both local testing and production deployment.

### Why this matters

The `Dockerfile` builds the container directly from `app/`:
```dockerfile
COPY app/ .          # copies app/ contents into /app in the container
CMD ["uvicorn", "server:app", ...]
```
If you edit a file outside `assets/btp-usage-agent/app/`, **it will never reach
the deployed container.**

---

## Local Development

### 1. Set up credentials

```bash
cd assets/btp-usage-agent/app
cp .env.example .env
# Fill in .env with your real credentials
```

### 2. Install dependencies

```bash
pip install -r ../requirements.txt
pip install "fastapi>=0.111.0" "uvicorn[standard]>=0.29.0"
```

### 3. Run the CLI (interactive chat)

```bash
cd assets/btp-usage-agent/app
python main.py --cli
```

### 4. Run the HTTP server locally

```bash
cd assets/btp-usage-agent/app
uvicorn server:app --host 0.0.0.0 --port 5001 --reload
```

---

## LLM Backend

| Backend | `LLM_BACKEND` value | Use case |
|---|---|---|
| SAP AI Core | `aicore` (default) | Production & normal development |
| LiteLLM / OpenAI | `openai` | Local testing with a local proxy |

To switch to LiteLLM locally, edit `.env`:
```
LLM_BACKEND=openai
LLM_API_KEY=<your-litellm-key>
LLM_BASE_URL=http://localhost:6655/litellm/v1
LLM_MODEL=anthropic--claude-sonnet-latest
```

> **Note:** `generative-ai-hub-sdk` is NOT used in this project. The build
> environment's network firewall blocks it. Authentication with SAP AI Core
> is handled via direct XSUAA OAuth2.0 calls in `llm_client.py`.

---

## Deployment

Deployment is managed by the SAP Build platform via `solution.yaml`.

```
solution.yaml  -->  assets/btp-usage-agent/asset.yaml  -->  Dockerfile  -->  app/
```

To deploy, use the SAP Build deploy action or the `joulework-cli`:
```bash
jl solution build && jl solution deploy <build-output>
```

---

## Security

- `.env` is for **local use only** -- never commit it to version control
- Add `.env` to `.gitignore` if not already present
- In production, credentials are injected via Kubernetes secrets by the platform
- The `.env` file is excluded from the Docker image via `COPY app/ .`
  (only `app/` contents are copied, not root-level files)

---

## Adding New Features

| What you want to do | Where to make changes |
|---|---|
| Add a new BTP API tool | `assets/btp-usage-agent/app/tools/` |
| Change LLM behaviour | `assets/btp-usage-agent/app/agent.py` |
| Add a new config variable | `assets/btp-usage-agent/app/config.py` + `.env.example` |
| Add a Python dependency | `assets/btp-usage-agent/requirements.txt` |
| Change health probe / port | `assets/btp-usage-agent/asset.yaml` |
| Change container build | `assets/btp-usage-agent/Dockerfile` |
