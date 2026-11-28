# Sakura AI — Live Demonstration Playbook (5-Minute & 15-Minute Editions)

This playbook provides a repeatable, zero-improvisation guide for demonstrating **Sakura AI** during college project evaluations, faculty vivas, recruiter calls, and technical interviews. Every step uses real running features—never simulated or mocked behavior presented as live production.

---

## 1. Repeatable Demonstration Environment Setup

### 1.1 Pre-Included Demo Assets (`docs/demo_assets/`)
- **Sample RAG Canary Document:** [`docs/demo_assets/sample_knowledge_base.md`](demo_assets/sample_knowledge_base.md) — Contains unique non-public synthetic facts (`Quantum Orchid Telemetry Gateway`, TCP port `7741`, `Sapphire-7` cooling, escalation code `ORCHID-ALPHA-42`) to prove real retrieval rather than LLM guesswork.
- **Sample Coding Module:** [`docs/demo_assets/sample_coding_repo/calculator.py`](demo_assets/sample_coding_repo/calculator.py) — Clean Python module for live Sakura Code inspection, diff, and test generation.
- **Automated Pre-Flight Health Script:** [`docs/demo_assets/preflight_check.py`](demo_assets/preflight_check.py) — Verifies `/health`, `/readiness` (Alembic revision `j9f7a263b56c`), `/api/v1/capabilities`, frontend pages, `/_next/image` hardening (`404`), and proxy routing in under 3 seconds.

### 1.2 Startup Commands (Local Demonstration Stack)

**Terminal 1 — FastAPI Backend (`http://127.0.0.1:8000`):**
```powershell
cd anime-ai/backend
python -m alembic upgrade head
$env:ENVIRONMENT="development"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Next.js Frontend (`http://localhost:3000`):**
```powershell
cd anime-ai/frontend
$env:SAKURA_API_PROXY_TARGET="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
npm run dev
```

**Terminal 3 — Optional Standalone Worker (for live background indexing/outbox):**
```powershell
cd anime-ai/backend
python -m tasks.worker
```

**Terminal 4 — Pre-Flight Verification (Run 2 Minutes Before Presenting):**
```powershell
python docs/demo_assets/preflight_check.py
```
Expected final line: `PRE-FLIGHT RESULT: READY FOR DEMO`.

### 1.3 Demo Account & Post-Demo Cleanup
- Create a clean dedicated demo account (e.g., `demo_evaluator`) on `/login` (`Sign up`) before presenting—never use personal credentials on screen.
- After presenting, remove the temporary account cleanly via Account Menu -> Delete Account (`DELETE /api/v1/auth/me` with `"DELETE"` confirmation) so no stray demo data remains.

---

## 2. Short Demonstration Plan — 5 Minutes
*Ideal for recruiter screens, initial technical interviews, and brief academic checkpoints.*

| Step & Duration | Exact Actions | Expected Visible Result | Technical Explanation | Dependencies & Failure Recovery |
| --- | --- | --- | --- | --- |
| **1. Intro & Landing (0:45)** | Open `http://localhost:3000/`. Highlight capability overview and open `http://127.0.0.1:8000/readiness` in a second tab. | Responsive dark UI loads cleanly; `/readiness` shows `database: CONNECTED`, `schema_revision: j9f7a263b56c`, and truthful `redis` status. | Explains 10-service architecture (`Next.js 14`, `FastAPI`, `PG15 + pgvector`, `Redis 7`, remote Docker sandbox) and truthful readiness reporting. | **Deps:** Local FE + BE. **Recovery:** Re-run `preflight_check.py`; if BE down, restart uvicorn. |
| **2. Authentication (0:45)** | Navigate to `/login`, sign in with demo account, then refresh `/chat`. | Redirects cleanly into `/chat`; session persists across reload; `Authorization: Bearer` header used (no URL tokens). | `PyJWT` (`HS256`), `pbkdf2_sha256` hashing, single-use 60s WebSocket tickets, header-only file downloads. | **Deps:** Migrated SQLite/PG DB. **Recovery:** Register a fresh `demo_eval2` user in 10 seconds. |
| **3. Live AI Conversation (1:00)** | Type: *"In 3 bullets, explain why combining pgvector with BM25 beats dense-only RAG."* Watch tokens stream. | Real incremental SSE token streaming; conversation saved in sidebar and persists on refresh. | Intent-routed `LLMRouter` (`Groq`/`OpenAI`/`Anthropic`/`Ollama`), transient-only failover, fail-closed `local_private` boundary. | **Deps:** Active `GROQ_API_KEY` (or other LLM key). **Recovery:** Show persisted conversation + open `llm/router.py` if internet drops. |
| **4. Document Intelligence (1:00)** | Click **Library** -> **Upload a file** -> select `docs/demo_assets/sample_knowledge_base.md` -> preview file. | File uploads to `StorageBackend` (`users/<uid>/...`), renders via authenticated preview, and queues indexing. | `pdfplumber`/text parser (800-char/150-overlap), `pgvector(1536)` + Okapi BM25 + RRF, async `HTTP 202` outbox delete. | **Deps:** Local FS or S3. **Recovery:** Demonstrate live BM25 canary test in terminal (`7741`, `Sapphire-7`). |
| **5. Sakura Coding Engine (1:00)** | Open `/console` or `http://127.0.0.1:8000/docs#/coding` and show workspace/tool isolation + GitHub Actions Run `46167864598` Docker E2E pass. | Live workspace endpoints & green CI job proving real non-root `UID 1001` Docker container execution with `0` orphaned containers. | Separate `coding-worker` calls remote `sandbox-executor` (sole `/var/run/docker.sock` host); `--network none` + single-use HMAC capability tokens. | **Deps:** Docker daemon (or CI Run `46167864598` evidence if Docker stopped locally). |
| **6. Architecture Wrap-Up (0:30)** | Flash Slide 8 (`System Architecture`) & Slide 15 (`Testing & Results`) of `presentation/Sakura_AI_Academic_Presentation.pptx`. | Clean 10-service blueprint + verified numbers (253 local tests, 4/4 CI jobs). | Summarizes durability, security, and next staging step. | **Deps:** Local `.pptx` file. |

---

## 3. Full Demonstration Plan — 15 Minutes
*Designed for final-year college evaluation panels, project guides, and deep-dive engineering interviews.*

| Step & Duration | Exact Actions | Expected Visible Result | Technical Explanation | Dependencies | Possible Failure & Recovery |
| --- | --- | --- | --- | --- | --- |
| **1. Problem & Intro (1:30)** | Open `http://localhost:3000/` and briefly show Slides 1–4 of the presentation. | Crisp landing page & clear engineering objectives. | Frames Sakura AI as solving durability, hybrid retrieval, tenant isolation, and safe code execution gaps. | Local FE (`:3000`) | If FE port busy, launch on `:3001` or show `docs/assets/screenshots/01_landing.png`. |
| **2. Auth, Quotas & Security (1:30)** | Open `/login`, test invalid password (shows clean error), sign in with demo user, refresh `/chat`, and open `/api/v1/auth/me/quotas` in Swagger `/docs`. | Clean error feedback; persistent authenticated session; atomic daily quotas (`chat: 500`, `image: 50`, `coding: 50`, `upload: 100`). | Explains `PyJWT` (`HS256`), fail-closed Redis rate limits (`503`), header-only Bearer file auth (`?token=` -> `401`), and single-use WS tickets. | BE (`:8000`) + DB | If DB unmigrated, run `python -m alembic upgrade head` and restart uvicorn. |
| **3. Streaming Chat & Sharing (2:00)** | Send a live prompt in `/chat`, pin the conversation, search it (`Search chats`), and click **Share** to generate a public `/share/[token]` link. | Real SSE streaming response (`Groq`), pinned badge, search hit, read-only shared page loads without auth, and revoking returns `404`. | Explains SSE unbuffered streaming, `messages` persistence, `conversation_shares` revocation, and `LLMRouter` failover/private Ollama boundary. | Active `GROQ_API_KEY` + internet | If internet/Groq rate-limited: show existing persisted conversation + `test_fail_closed_security_regression.py` timeout/privacy tests. |
| **4. Document Upload & Hybrid RAG (2:00)** | Open **Library**, upload `docs/demo_assets/sample_knowledge_base.md`, open preview, and ask about `Quantum Orchid port 7741` (or show live BM25 canary test). Delete a test file to show `HTTP 202`. | Preview displays exact file via Bearer auth; BM25/Hybrid RAG retrieves `7741` and `Sapphire-7`; delete triggers `StorageDeletionOutbox` (`202`). | Explains `vector(1536)` on PostgreSQL (`JSON` on SQLite), Okapi BM25 (`k1=1.5, b=0.75`), Reciprocal Rank Fusion, `index_generation` fencing, and killable subprocess storage delete. | BE + Storage (worker optional for async indexing) | If `OPENAI_API_KEY` unset: explicitly state honest BM25 lexical fallback (`embedding = NULL`, zero fake vectors). |
| **5. Multimodal Media & Idempotency (1:30)** | Open Image Generation modal (or `/docs` `POST /api/v1/images/jobs`) with an explicit `idempotency_key`; submit twice. Show `/api/v1/capabilities`. | Second identical submission returns the exact same `job_id` without duplicate quota charge; `/capabilities` truthfully reports `image_conditioned_edit: false`. | Explains `ImageGenerationRouter`, `image_variation_batches` canonical `request_fingerprint` (`409` on payload mismatch), and truthful capability flags. | BE + Pollinations (optional for live render) | If Pollinations unreachable/slow: demonstrate durable job queueing + idempotency deduplication without waiting on external image host. |
| **6. Durable Workers & Scheduled Tasks (1:30)** | Click **Scheduled** in sidebar, create a cron task (`0 9 * * *`, `Asia/Kolkata`), toggle pause/resume, and inspect `/api/v1/tasks` rejecting forged `storage_delete` (`400`). | Scheduled task persists with computed `next_run_at`; forged internal task type blocked with `400`. | Explains PostgreSQL `FOR UPDATE SKIP LOCKED`, `execution_attempt_id` + `lease_expires_at > NOW()` lease fencing, and unique `(task_id, scheduled_for)` constraint. | BE + DB | Show `test_postgres_pgvector_and_concurrency.py` CI pass for multi-worker concurrency proof. |
| **7. Sakura Coding Engine (2:00)** | Show workspace creation, file write/read/diff (`calculator.py`), path traversal attempt (`../../.env` blocked), and durable coding task submission + event replay (`after_sequence`). | Clean file read/write & diff; traversal blocked with security error; durable coding job & event log created. | Explains `CodingToolchain`, `coding_jobs`, sequential `coding_task_events` SSE replay, and cooperative cancellation. | BE + Coding Workspace | If `coding-worker` isn't running locally, demonstrate workspace tools live and show CI Run `46167864598` full worker execution. |
| **8. Docker Sandbox Isolation (1:30)** | Open `docs/architecture/CODING_SANDBOX_WORKFLOW.md` + GitHub Actions Run `46167864598` -> `Docker Sandbox E2E Integration` job log. | All steps green, including `Verify Zero Orphaned Sandbox Child Containers`. | Explains `/var/run/docker.sock` isolated solely to `sandbox-executor`, `--user 1001:1001`, `--network none`, `--cap-drop ALL`, `2 CPU / 512 MB / 64 PIDs`, and single-use HMAC capability tokens. | Internet (or local Slide 12 + `docs/testing/SECURITY_VERIFICATION.md` offline) | If offline: present Slide 12 & `docs/testing/UAT_TEST_RESULTS.md`. |
| **9. Architecture & Database (1:00)** | Show `docs/architecture/SYSTEM_ARCHITECTURE.md` and `DATABASE_ER_DIAGRAM.md` (32 tables, 11 Alembic migrations). | Clear 10-service topology and 32-table ER schema. | Highlights why `pgvector` inside PostgreSQL guarantees ACID tenant deletion and why `account_audit_events` omits a cascading FK. | Local Markdown / Slides 8–9 | Zero external dependency. |
| **10. Testing Evidence & Limitations (0:30)** | Show `docs/testing/UAT_TEST_RESULTS.md` and Slide 15–16. | Exact verified counts (253 local unit tests, live UAT results, 4/4 CI jobs) and honest known limitations. | Reinforces engineering rigor and transitions cleanly to viva Q&A. | Local docs / Slides 15–16 | Zero external dependency. |

---

## 4. Fallback Matrix for External Service Outages

| Unavailable Component | Honest Disclosure to Audience | Immediate Live Recovery Action |
| --- | --- | --- |
| **No Internet / Groq / OpenAI Down** | *"External LLM APIs are offline on this network; let me show our persisted conversation history, local BM25 RAG retrieval, security guards, and verified CI evidence."* | Run `python docs/demo_assets/preflight_check.py`, show persisted chat/library/coding tools locally, and run `unittest` on `test_fail_closed_security_regression.py`. |
| **No `OPENAI_API_KEY` Configured** | *"Dense OpenAI embeddings and Whisper STT are optional; Sakura AI detects their absence truthfully via `/api/v1/capabilities` and falls back to Okapi BM25 without generating fake vectors."* | Demonstrate live `/api/v1/capabilities` and BM25 canary retrieval on `sample_knowledge_base.md`. |
| **No SMTP Server Configured** | *"SMTP credentials are intentionally omitted in local dev; the reset endpoint validates input cleanly without exposing tokens."* | Show `services/email.py` and `test_auth_security.py` unit verification. |
| **Docker Desktop Stopped Locally** | *"Docker Desktop is not running on this Windows laptop; in production mode Sakura AI refuses host fallback, and real non-root Docker sandbox E2E runs continuously in Linux CI."* | Open GitHub Actions Run `46167864598` (`Docker Sandbox E2E Integration` & `Full-Stack Integration Tests`) + `docs/architecture/CODING_SANDBOX_WORKFLOW.md`. |
| **Pollinations Image Host Slow/Down** | *"External raster generation is decoupled from API requests via `image_generation_jobs` with bounded retries and idempotency keys."* | Demonstrate durable job creation (`HTTP 202`), idempotency replay deduplication, and job status polling. |
