# Sakura AI — System Requirements Specification (SRS)

> Companion standalone specification to Chapter 3 of [`PROJECT_REPORT.md`](PROJECT_REPORT.md).

---

## 1. Functional Requirements

| ID | Category | Requirement Description | Implementation Status |
| --- | --- | --- | --- |
| **FR-01** | Authentication | Users can register (password strength >= 8 chars), authenticate via `PyJWT` (`HS256`), request/confirm SMTP password resets, export account data (ZIP), and permanently delete accounts (`DELETE /api/v1/auth/me` with password + `"DELETE"` confirmation). | **Implemented & Verified** |
| **FR-02** | Conversational AI | Authenticated users can create, rename, pin, archive, search, share (`/share/{token}`), and delete conversations, with real-time SSE token streaming (`POST /api/v1/chat/stream`), message feedback, and extracted long-term user memories. | **Implemented & Verified** |
| **FR-03** | Multi-Provider Routing | Backend routes prompts across Groq, OpenAI, Anthropic, and local Ollama based on intent, failing over only on transient errors (`429`, `5xx`, timeouts) and failing closed on private intents when Ollama is unconfigured. | **Implemented & Verified** |
| **FR-04** | Document & Library Management | Users can upload files (`PDF`, `MD`, `TXT`, code, images) into S3-compatible or local storage, preview/download strictly via `Authorization: Bearer` headers, toggle knowledge-base indexing, and trigger asynchronous deletion (`HTTP 202`). | **Implemented & Verified** |
| **FR-05** | Hybrid RAG | Uploaded documents are parsed (`pdfplumber`/text), chunked (800 chars, 150 overlap), embedded (`text-embedding-3-small`, 1536-d when configured), and retrieved per user using `pgvector` cosine distance + Okapi BM25 + RRF. | **Implemented & Verified** |
| **FR-06** | Image Generation | Users can submit asynchronous text-to-image, edit, and idempotent variation jobs (`Idempotency-Key` deduplication + payload fingerprint mismatch `HTTP 409`), automatically synchronized with the user's Library. | **Implemented & Verified** |
| **FR-07** | Audio Transcription | Authenticated users can upload audio files (up to 25 MB; `.webm`, `.wav`, `.mp3`, `.m4a`, `.ogg`, `.mp4`, `.flac`) for speech-to-text transcription via OpenAI Whisper (`POST /api/v1/audio/transcribe`). | **Implemented (Requires `OPENAI_API_KEY`)** |
| **FR-08** | Projects & Integrations | Users can organize conversations, files, and repositories inside Projects (`api/projects.py`) and connect verified GitHub tokens (`api/integrations.py`); unimplemented third-party connectors return `HTTP 501`. | **Implemented (GitHub Live; Others Honest 501)** |
| **FR-09** | Scheduled & Background Tasks | Users can create cron-scheduled tasks with IANA timezones (`api/scheduled.py`) and allowed background jobs (`web_research`, `doc_summary`, `code_analysis`, `dataset_analysis`) while forged internal task types are rejected (`HTTP 400`). | **Implemented & Verified** |
| **FR-10** | Sakura Coding Engine | Users can create isolated repository workspaces, enqueue durable coding tasks, stream live tool/diff/verification events over SSE, cancel running jobs, and authorize single-use network commands. | **Implemented & Verified (CI Docker E2E)** |
| **FR-11** | Quotas & Real-Time Events | System enforces atomic UTC-day per-user quotas (`chat: 500`, `image_generation: 50`, `coding_task: 50`, `file_upload: 100`, `scheduled_job: 30`) and pushes real-time updates over single-use ticket-authenticated WebSockets. | **Implemented & Verified** |

---

## 2. Non-Functional Requirements

| Category | Specification | Verification Evidence |
| --- | --- | --- |
| **Security & Multi-Tenancy** | Every tenant-owned entity enforces `user_id` ownership checks; cross-tenant access returns `404`; zero JWTs permitted in URLs (`?token=` returns `401`); child containers run as non-root `1001:1001` with `--network none` and `--cap-drop ALL`. | Verified in 22-test fail-closed security suite, live 37/37 checks, and CI Docker Sandbox E2E. |
| **Durability & Fault Tolerance** | Worker crashes must not lose jobs or corrupt terminal states; expired leases are recovered atomically; stale workers are fenced out via `execution_attempt_id` / `claim_token` + `lease_expires_at > NOW()`. | Verified on real PostgreSQL 15 in `test_postgres_pgvector_and_concurrency.py` & `test_worker_and_outbox_fencing.py`. |
| **Reliability & Observability** | Every HTTP response carries `X-Request-ID`; `/health` reports liveness; `/readiness` truthfully checks DB connectivity, Alembic head revision (`j9f7a263b56c`), Redis status, storage backend, and production secret guards. | Verified in `test_capabilities_truthfulness.py` and live `/readiness` probe. |
| **Resource Boundedness** | Docker sandbox containers are capped at `2.0` CPUs, `512 MB` RAM, `64` PIDs, `100,000` chars stdout/stderr, and strict timeouts with kill-before-remove cleanup (`0` orphaned containers). | Verified in GitHub Actions `Docker Sandbox E2E Integration` & `Full-Stack Integration Tests`. |
| **Maintainability & Portability** | Dialect-aware SQLAlchemy models (`vector(1536)` on PostgreSQL, `JSON` on SQLite) allow frictionless local development while enforcing full PostgreSQL 15 parity in CI and production. | Verified in `test_schema_parity.py` on both SQLite and PostgreSQL 15. |

---

## 3. Hardware, Software & External Service Requirements

### 3.1 Minimum & Recommended Hardware
- **Local Development Machine:** 64-bit x86_64/ARM64 CPU (4 cores recommended), 8 GB RAM (16 GB recommended when running Docker Desktop + PostgreSQL + Redis + Ollama), 10 GB free disk space.
- **Staging / Production Server (Docker Topology):** 4+ vCPUs, 8–16 GB RAM (separated host recommended for `sandbox-executor` isolating `/var/run/docker.sock`), 40+ GB SSD storage, HTTPS domain & TLS certificates.

### 3.2 Software Stack Requirements
- **OS:** Linux (Ubuntu 22.04/24.04 LTS for staging/CI) or Windows 10/11 / macOS for local development.
- **Runtime:** Python 3.11+ (tested on Python 3.11 in CI and Python 3.14 locally), Node.js 20/22 LTS + `npm`.
- **Data & Container Engines:** PostgreSQL 15 with `pgvector` extension (`pgvector/pgvector:pg15`), Redis 7 (`redis:7-alpine`), Docker Engine + Docker Compose v2, Nginx 1.24+ (for TLS reverse proxying).

### 3.3 External Service Requirements
- **Required for Live AI Responses:** At least one configured LLM provider (`GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or local `OLLAMA_BASE_URL`).
- **Optional Feature Providers:** `OPENAI_API_KEY` (1536-d `text-embedding-3-small` dense RAG & Whisper audio transcription), `TAVILY_API_KEY` (web search; DuckDuckGo fallback available), Pollinations endpoint (raster image generation), S3-compatible bucket (AWS S3 / Cloudflare R2 / MinIO), and SMTP server (password reset emails).
