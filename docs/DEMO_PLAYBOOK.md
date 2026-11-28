# Sakura AI — Repeatable Live Demonstration Playbook

> **Audience:** College faculty evaluators, capstone examiners, and technical interviewers.  
> **Target Duration:** 12–15 minutes (including 3 minutes of architecture walkthrough).

---

## 1. Pre-Demo Checklist & Dependencies

### Required Local Environment
- **Backend:** Python 3.11+ with `anime-ai/backend/venv` (or system Python with `requirements.txt` installed)
- **Frontend:** Node.js 20+ with `anime-ai/frontend/node_modules` installed (`npm ci`)
- **Database:** Local SQLite migrated to head (`python -m alembic upgrade head` inside `anime-ai/backend`) — *or* PostgreSQL 15 + `pgvector` + Redis 7 via Docker Compose for full production-topology demos.
- **Recommended Env Vars (`anime-ai/backend/.env`):**
  - `ENVIRONMENT=development`
  - `DATABASE_URL=sqlite:///./anime_ai.db`
  - `JWT_SECRET` (>= 32 chars)
  - `GROQ_API_KEY` or `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (for live LLM chat; `OPENAI_API_KEY` also enables live 1536-dim RAG embeddings)
  - `TAVILY_API_KEY` (optional; DuckDuckGo fallback active if unset)

### Quick Startup Commands (Windows PowerShell)

**Terminal 1 — Backend API (`http://127.0.0.1:8000`):**
```powershell
cd anime-ai\backend
python -m alembic upgrade head
$env:ENVIRONMENT="development"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Frontend UI (`http://localhost:3000`):**
```powershell
cd anime-ai\frontend
$env:SAKURA_API_PROXY_TARGET="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
npm run dev
```

**Pre-Demo Health Check (30 seconds before presenting):**
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/readiness
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/login
```

---

## 2. Step-by-Step 15-Minute Demo Sequence

### Step 1 — Product Introduction & Public Landing (1 min)
- Open **http://localhost:3000**.
- Highlight the platform scope: multi-agent AI workspace combining streaming chat, Hybrid RAG, multimodal Library, scheduled automation, and an isolated coding engine.
- Briefly point out `/health` and `/readiness` (deep dependency health probe without leaking secrets).

### Step 2 — Authentication & Multi-Tenant Security (2 min)
- Navigate to **http://localhost:3000/login** and register a fresh demo account (e.g., `demo_eval@example.com`).
- Explain: passwords hashed via `pbkdf2_sha256`, tokens signed via `PyJWT` (`HS256`), WebSockets authenticated via single-use hashed tickets (`POST /api/v1/auth/ws-ticket`), and file downloads enforcing header-only `Authorization: Bearer` (no JWTs in URLs).
- Show Swagger API docs at **http://127.0.0.1:8000/docs** if evaluators want to see typed OpenAPI contracts.

### Step 3 — Live AI Conversation & SSE Streaming (2 min)
- Start a new conversation in `/chat` and send a technical prompt (e.g., *"Explain how Reciprocal Rank Fusion improves hybrid RAG retrieval in 4 concise bullet points."*).
- Point out progressive Server-Sent Events (SSE) token streaming (`X-Accel-Buffering: no`), then refresh the browser to prove PostgreSQL/SQLite persistence.

### Step 4 — Document Intelligence & Hybrid RAG (2.5 min)
- Open **Library**, upload a prepared sample `.txt` or `.md` file containing a unique project fact (e.g., *"Project Sakura uses vector(1536) embeddings fused with Okapi BM25 k1=1.5."*).
- Preview the file in `FilePreviewModal` and download it (point out `AuthenticatedImage` / `authFetch` Blob URLs — zero 401s and zero query-string tokens).
- Enable **Add to AI Index** and ask a question in `/chat` referencing that uploaded document to show grounded retrieval.

### Step 5 — Multimodal Media & Async Deletion Outbox (2 min)
- Open **Generate Image** in Library (or explain the durable `ImageGenerationJob` + `idempotency_key` flow if external Pollinations is rate-limited).
- Click **Delete** on a demo file to demonstrate `HTTP 202 DELETING` asynchronous deletion backed by `StorageDeletionOutbox` + killable subprocess cleanup + real-time UI reconciliation.

### Step 6 — Sakura Code & Sandbox Isolation (2.5 min)
- Open the **Coding Workspace** panel (or use `/code` in chat) and create an isolated workspace.
- Explain how production mode enforces `RemoteHttpSandboxRuntime` -> `sandbox-executor` (`:9000`) -> ephemeral non-root (`1001:1001`) Docker containers with `--network none`, `--cap-drop ALL`, single-use Redis-fenced HMAC capability tokens, and `0` orphaned containers verified in GitHub CI.

### Step 7 — Background Tasks, Quotas & Architecture Walkthrough (3 min)
- Open **Scheduled Tasks** (show IANA timezone cron scheduling + daily quota enforcement) and **Account Settings** (show daily usage quota summary, async ZIP data export, and self-service account deletion).
- Open [`docs/ACADEMIC_PROJECT_REPORT.md`](ACADEMIC_PROJECT_REPORT.md) or GitHub Actions CI Run (`4/4 PASSED`) to show real PostgreSQL 15 + `pgvector` migrations, backup/restore verification, and full-stack Playwright E2E evidence.

---

## 3. Fallback Plan for Unavailable External Services

| Failure Scenario During Live Demo | Immediate Fallback Action |
| --- | --- |
| **LLM API key rate-limited / Wi-Fi down** | Start backend with `$env:ENVIRONMENT="test"; $env:SAKURA_DETERMINISTIC_TEST_PROVIDERS="1"` (strictly for offline demo — rejected by `validate_env.py` in production) so chat, RAG, scheduled runs, and coding workflows run 100% offline deterministically. |
| **OpenAI Embeddings unavailable** | Hybrid RAG automatically degrades cleanly to Okapi BM25 lexical scoring with zero errors and reports truthful capability status on `/api/v1/capabilities`. |
| **Docker Desktop not running locally** | Demonstrate workspace creation, security policy validation, and coding API locally, then show the live passing **Docker Sandbox E2E Integration** and **Full-Stack Integration Tests** CI logs on GitHub Actions. |
| **Pollinations image upstream slow/offline** | Show `GenerateImageModal` retry-stable `idempotency_key` handling and demonstrate the passing `test_image_variation_idempotency_regression.py` suite (`400` / `202` / `409` / quota checks). |
| **SMTP not configured locally** | Show `/api/v1/auth/config` truthfully reporting `password_reset_enabled: false` (fail-closed honesty rather than fake success). |
