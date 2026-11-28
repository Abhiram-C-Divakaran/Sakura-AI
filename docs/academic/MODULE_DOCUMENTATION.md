# Sakura AI — Comprehensive Module Documentation

> Companion standalone document to Chapter 6 of [`PROJECT_REPORT.md`](PROJECT_REPORT.md). Every module below documents its actual implemented purpose, internal workflow, backend files, frontend components, database tables, external dependencies, and verified implementation status.

---

## Module 1: User Authentication & Account Lifecycle
1. **Purpose:** Secure identity registration, login, password recovery, data portability (ZIP export), and permanent self-service account deletion with audit logging.
2. **Internal Workflow:** Password registration validates complexity (>= 8 chars) and hashes via Passlib `pbkdf2_sha256`. Login issues signed `PyJWT` (`HS256`) access tokens validated by `AuthManager.get_current_user`. Password reset stores only SHA-256 hashes of single-use tokens in `password_reset_tokens`. `DELETE /api/v1/auth/me` verifies password + `"DELETE"` confirmation, cancels active jobs, queues/purges storage keys, deletes user records, and writes an immutable `account_audit_events` row.
3. **Backend Components:** `auth/manager.py`, `auth/authorization.py`, `auth/crypto.py`, `api/routes.py`, `services/account.py`, `services/email.py`.
4. **Frontend Components:** `pages/login.tsx`, `components/app/AccountMenu.tsx`, `lib/api.ts` (`authFetch`).
5. **Database Interactions:** `users`, `password_reset_tokens`, `websocket_tickets`, `user_data_exports`, `account_audit_events`.
6. **External Dependencies:** `PyJWT`, `passlib`, optional SMTP server for reset emails, Redis (auth rate limits).
7. **Implementation Status:** **Implemented & Verified** (local tests, live smoke checks, and CI).

---

## Module 2: AI Conversational System & Multi-Provider Router
1. **Purpose:** Deliver low-latency streaming AI conversations with intent-aware multi-provider routing, transient failover, character personas, and fail-closed privacy mode.
2. **Internal Workflow:** `POST /api/v1/chat/stream` enforces daily `chat` quotas, loads conversation history, memories, RAG chunks, and optional web search, selects an ordered provider list via `LLMRouter.get_ordered_providers(intent)`, streams SSE tokens with bounded timeouts, and fails over only on transient errors (`429`, `5xx`, timeout, network). `local_private` / `private_data` intents restrict routing strictly to Ollama and raise `PrivateModelUnavailableError` if unconfigured.
3. **Backend Components:** `llm/router.py`, `llm/agent.py`, `llm/providers/{openai,anthropic,groq,ollama,base,deterministic_test}.py`, `characters/engine.py`, `services/web_search.py`.
4. **Frontend Components:** `pages/chat.tsx`, `components/app/ConversationView.tsx`, `components/ChatComposer.tsx`, `components/IntensityDropdown.tsx`.
5. **Database Interactions:** `conversations`, `messages`, `characters`, `user_memories`, `user_usage_quotas`.
6. **External Dependencies:** Configured LLM API (`GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OLLAMA_BASE_URL`), optional `TAVILY_API_KEY` / DuckDuckGo.
7. **Implementation Status:** **Implemented & Verified** (requires at least one configured provider key for live completions; deterministic provider verified in CI).

---

## Module 3: Conversation Persistence, Sharing & Long-Term Memory
1. **Purpose:** Persist multi-turn conversations across sessions with pinning, archiving, full-text search, message feedback, read-only public sharing, and extracted user preferences.
2. **Internal Workflow:** Every user/assistant message is committed to `messages` with JSON metadata. Users can pin, archive, search (`/conversations/search`), submit feedback (`message_feedbacks`), and generate revocable share tokens (`/share/{token}`). `MemoryManager` extracts and stores scoped long-term facts in `user_memories` retrievable or deletable by the user.
3. **Backend Components:** `api/routes.py`, `memory/manager.py`, `auth/authorization.py`.
4. **Frontend Components:** `components/app/Sidebar.tsx`, `components/SearchModal.tsx`, `components/ChatModals.tsx`, `pages/share/[token].tsx`.
5. **Database Interactions:** `conversations`, `messages`, `message_feedbacks`, `conversation_shares`, `user_memories`.
6. **External Dependencies:** PostgreSQL 15 (or SQLite in local dev).
7. **Implementation Status:** **Implemented & Verified** (including cross-user `404` isolation and malformed UUID `400` checks).

---

## Module 4: Document & File Library Management
1. **Purpose:** Provide a unified, multi-tenant file repository for uploads, inline document creation, authenticated previews/downloads, and crash-safe asynchronous storage deletion.
2. **Internal Workflow:** Uploads validate size/MIME/quota and write to `StorageBackend` under `users/<user_id>/...`. Downloads and thumbnails (`/api/v1/library/files/{id}/download`, `/thumbnail`) enforce header-only `Authorization: Bearer` authentication (`?token=` rejected with `401`) and `user_id` ownership (`404` on mismatch). Deletion marks `deletion_status='DELETING'`, enqueues `storage_deletion_outbox`, returns `HTTP 202`, and purges objects asynchronously via a killable subprocess runner.
3. **Backend Components:** `api/library.py`, `services/documents.py`, `services/storage.py`, `services/storage_delete_runner.py`, `services/upload.py`.
4. **Frontend Components:** `components/LibraryView.tsx`, `components/FileLibraryModal.tsx`, `components/FilePreviewModal.tsx`, `components/ConversationFilesSheet.tsx`, `components/CreateDocumentModal.tsx`, `components/AuthenticatedImage.tsx`.
5. **Database Interactions:** `documents`, `document_chunks`, `storage_deletion_outbox`, `project_files`.
6. **External Dependencies:** Local filesystem (`LocalFilesystemStorage`) or S3-compatible bucket (`S3CompatibleStorage` via `boto3`).
7. **Implementation Status:** **Implemented & Verified** (local tests, live 37/37 checks, and CI).

---

## Module 5: Document Intelligence & Parsing Pipeline
1. **Purpose:** Extract clean plain text from user-uploaded PDFs, Markdown, plain text, and source code files and prepare overlapping passages for downstream search.
2. **Internal Workflow:** `DocumentParser` (`rag/ingestion/parser.py`) reads files retrieved from storage, extracts page-by-page text from PDFs via `pdfplumber` (or UTF-8 decoding for text/Markdown/code), cleans whitespace, and splits text into overlapping chunks (`chunk_size=800`, `chunk_overlap=150`). `index_generation` fencing prevents stale worker retries from overwriting newer re-index runs or resurrecting deleted documents.
3. **Backend Components:** `rag/ingestion/parser.py`, `services/documents.py`, `tasks/worker.py`.
4. **Frontend Components:** `components/LibraryView.tsx` (indexing status badges & toggle), `components/AttachmentChips.tsx`.
5. **Database Interactions:** `documents` (`indexing_status`, `index_generation`, `is_knowledge_base`), `document_chunks`.
6. **External Dependencies:** `pdfplumber`.
7. **Implementation Status:** **Implemented & Verified**.

---

## Module 6: Hybrid Retrieval-Augmented Generation (RAG) & Vector Search
1. **Purpose:** Ground LLM responses in user-owned documents with high recall on both conceptual paraphrases and exact technical identifiers while enforcing zero cross-tenant leakage.
2. **Internal Workflow:** `EmbeddingManager` generates 1536-dimensional embeddings using OpenAI `text-embedding-3-small` (30s timeout) when `OPENAI_API_KEY` is present, or stores `NULL` honestly without random fake vectors. At query time, `rag/retrieval.py` filters strictly by `documents.user_id == current_user.id` and `deletion_status == 'ACTIVE'`, executes native PostgreSQL `pgvector` cosine distance (`<=>`) search alongside Okapi BM25 (`k1=1.5`, `b=0.75`), and combines rankings via Reciprocal Rank Fusion (RRF).
3. **Backend Components:** `rag/embeddings/manager.py`, `rag/retrieval.py`, `database/models.py` (`Vector(1536)`).
4. **Frontend Components:** `components/LibraryView.tsx`, `components/app/ContextPanel.tsx`, `components/ConversationFilesSheet.tsx`.
5. **Database Interactions:** `documents`, `document_chunks` (`embedding vector(1536)` on PostgreSQL / `JSON` on SQLite).
6. **External Dependencies:** PostgreSQL `pgvector` extension; optional `OPENAI_API_KEY` for dense embeddings (BM25 works offline).
7. **Implementation Status:** **Implemented & Verified** (real PostgreSQL 15 `pgvector(1536)` verified in CI with 0 skips).

---

## Module 7: Multimodal Image & Media Generation
1. **Purpose:** Generate raster artwork, UI mockups, prompt-context edits, and idempotent image variations asynchronously with full Library synchronization and lineage tracking.
2. **Internal Workflow:** `ImageGenerationRouter` classifies prompts (`ANIME`, `PHOTOREALISM`, `UI`, `VECTOR` only on explicit SVG request, `EDIT`, `UPSCALE`, `TEXT_TO_IMAGE`) and expands prompts with quality/negative constraints. Requests create durable `image_generation_jobs` (and `image_variation_batches` keyed by `idempotency_key` + `request_fingerprint`, rejecting mismatched reuse with `HTTP 409`). Standalone `image-worker` executes Pollinations raster calls with bounded retries (`QualityEvaluator`), stores PNG/WebP output in `StorageBackend`, and records `generated_images` + `documents` rows.
3. **Backend Components:** `media/image_engine.py`, `media/image_worker.py`, `api/routes.py`, `api/library.py`.
4. **Frontend Components:** `components/GenerateImageModal.tsx`, `components/ImageLightboxModal.tsx`, `components/AuthenticatedImage.tsx`.
5. **Database Interactions:** `image_generation_jobs`, `image_variation_batches`, `generated_images`, `documents`.
6. **External Dependencies:** Pollinations raster endpoint, `StorageBackend`, Redis wakeups.
7. **Implementation Status:** **Implemented & Verified** (note: variations/edits are prompt-context regenerations, truthfully flagged as `image_conditioned_edit: false` in `/api/v1/capabilities`).

---

## Module 8: Voice & Audio Transcription
1. **Purpose:** Enable spoken prompt capture in the browser and server-side speech-to-text transcription.
2. **Internal Workflow:** Browser `VoiceRecorder` captures microphone audio (`MediaRecorder`) and posts multipart audio to `POST /api/v1/audio/transcribe`. Backend validates extension allowlist (`.webm`, `.wav`, `.mp3`, `.m4a`, `.ogg`, `.mp4`, `.flac`, `.mpeg`, `.mpga`) and enforces the 25 MB Whisper hard cap before invoking OpenAI Whisper transcription (`AsyncOpenAI`).
3. **Backend Components:** `api/audio.py`.
4. **Frontend Components:** `components/VoiceRecorder.tsx`, `components/ChatComposer.tsx`.
5. **Database Interactions:** Authenticated user check (`users`).
6. **External Dependencies:** `OPENAI_API_KEY` (Whisper API).
7. **Implementation Status:** **Implemented** (requires `OPENAI_API_KEY` at runtime; returns clean configuration error when unset).

---

## Module 9: Durable Background Task Processing & Cron Scheduler
1. **Purpose:** Execute long-running asynchronous workloads (document indexing, research/analysis tasks, user data ZIP exports, storage deletion outbox, and recurring cron prompts) reliably across worker restarts.
2. **Internal Workflow:** FastAPI writes authoritative rows to PostgreSQL (`background_tasks`, `storage_deletion_outbox`, `scheduled_tasks`) and emits a best-effort Redis wakeup. Standalone `tasks/worker.py` claims jobs atomically via PostgreSQL `FOR UPDATE SKIP LOCKED` / CAS with `worker_id`, `execution_attempt_id`, and `lease_expires_at`, heartbeats active leases, enforces conditional terminal updates, and recovers stale expired leases. `tasks/scheduler.py` evaluates cron expressions in each task's IANA timezone and enforces unique `(task_id, scheduled_for)` rows in `scheduled_task_runs`. Public `POST /api/v1/tasks` restricts types to `ALLOWED_USER_TASK_TYPES` (`code_analysis`, `dataset_analysis`, `doc_summary`, `web_research`) and rejects forged internal types (`HTTP 400`).
3. **Backend Components:** `tasks/worker.py`, `tasks/task_manager.py`, `tasks/scheduler.py`, `api/routes.py`, `api/scheduled.py`.
4. **Frontend Components:** `components/ScheduledView.tsx`, `hooks/useTasks.ts`, `hooks/useRealtime.ts`.
5. **Database Interactions:** `background_tasks`, `scheduled_tasks`, `scheduled_task_runs`, `storage_deletion_outbox`, `user_data_exports`.
6. **External Dependencies:** PostgreSQL 15, Redis 7 (wakeups & Pub/Sub; DB poll fallback in dev).
7. **Implementation Status:** **Implemented & Verified** (concurrency, lease expiry, and outbox fencing verified on real PostgreSQL 15 in CI).

---

## Module 10: Sakura Coding Engine (Repository-Level Agent)
1. **Purpose:** Plan, inspect, edit, diff, and test multi-file codebases autonomously inside user-owned workspaces with real-time progress transparency.
2. **Internal Workflow:** Users create a workspace (`POST /api/v1/coding/workspaces`) and submit coding tasks (`POST /api/v1/coding/workspaces/{id}/tasks`). Standalone `coding/job_worker.py` claims `coding_jobs` with lease fencing and drives `coding/agent.py`, which invokes `CodingToolchain` (`coding/tools.py`: file read/write/patch, ripgrep/code search, git status/diff/branch, test/command execution) while writing sequential `coding_task_events` streamed to the UI over SSE (`/events/stream`) with `after_sequence` replay and cooperative cancellation (`cancel_requested`).
3. **Backend Components:** `api/coding.py`, `coding/agent.py`, `coding/job_worker.py`, `coding/tools.py`, `coding/patching.py`, `coding/code_search.py`, `coding/git_manager.py`, `coding/repository.py`, `coding/security.py`.
4. **Frontend Components:** `pages/console.tsx`, `components/coding/{CodingActivity,DiffSummary,DiffViewer,ToolExecution,VerificationSummary,WorkspaceSelector}.tsx`, `hooks/useCodingTaskStream.ts`.
5. **Database Interactions:** `repository_workspaces`, `coding_jobs`, `coding_tasks`, `coding_task_events`, `tool_executions`, `sandbox_network_authorizations`.
6. **External Dependencies:** Configured LLM provider, Remote Sandbox Executor (`coding/sandbox_service.py`), Docker Engine.
7. **Implementation Status:** **Implemented & Verified** (end-to-end separate worker + real Docker sandbox verified in CI).

---

## Module 11: Docker Sandbox Isolation Service
1. **Purpose:** Execute untrusted code, compilers, and test suites inside an isolated, non-root, network-disabled container boundary completely decoupled from backend credentials and host files.
2. **Internal Workflow:** `coding/sandbox_service.py` (port `9000`) is the sole service with `/var/run/docker.sock`. It verifies `X-Sandbox-Token`, validates strict workspace UUIDs (preventing path/symlink traversal), strips host secrets via environment allowlisting, and launches `docker run --rm --user 1001:1001 --network none --cpus=2.0 --memory=512m --pids-limit=64 --cap-drop ALL --security-opt no-new-privileges:true` mounting only the target workspace to `/workspace`. Outbound network access (`--network bridge`) requires a valid, single-use HMAC-SHA256 capability token bound to workspace ID, exact command hash, and expiry, consumed atomically in Redis (fail-closed if Redis is down). Timeouts trigger `docker kill` + `docker rm -f`.
3. **Backend Components:** `coding/sandbox.py`, `coding/sandbox_service.py`, `coding/capabilities.py`, `anime-ai/sandbox/Dockerfile`.
4. **Frontend Components:** Network authorization prompts & tool output previews in `components/coding/ToolExecution.tsx`.
5. **Database Interactions:** `sandbox_network_authorizations`.
6. **External Dependencies:** Docker Engine, Redis 7 (single-use capability nonce consumption).
7. **Implementation Status:** **Implemented & Verified** (CI verifies real non-root execution, network blocking, capability verification, and `0` orphaned containers).

---

## Module 12: Projects & External Integrations
1. **Purpose:** Group related conversations, files, custom system instructions, and Git repositories into structured project workspaces, and manage encrypted third-party API credentials.
2. **Internal Workflow:** `api/projects.py` manages user-scoped `projects` and links conversations, files, and repositories. `api/integrations.py` encrypts user-supplied GitHub tokens with Fernet (`INTEGRATION_ENCRYPTION_KEY`) in `auth/crypto.py`, validates them against the real GitHub API, and lists repositories (`GET /api/v1/integrations/github/repos`). Unimplemented providers (Google Drive, Notion, Slack, Jira, Postgres) return honest `HTTP 501`.
3. **Backend Components:** `api/projects.py`, `api/integrations.py`, `auth/crypto.py`.
4. **Frontend Components:** `components/ProjectsView.tsx`, `components/PluginsView.tsx`, `components/ConnectAppsModal.tsx`.
5. **Database Interactions:** `projects`, `project_conversations`, `project_files`, `project_repositories`, `user_integrations`.
6. **External Dependencies:** GitHub REST API (optional, user-initiated).
7. **Implementation Status:** **Implemented** (Projects & GitHub verified; non-GitHub connectors intentionally `501`).

---

## Module 13: Usage Quotas & Proxy-Aware Rate Limiting
1. **Purpose:** Prevent abuse, brute-force authentication attempts, and unbounded AI/compute cost spikes across multi-replica deployments.
2. **Internal Workflow:** `services/rate_limit.py` implements Redis-backed sliding-window limits with CIDR-validated `X-Forwarded-For` client IP resolution (`TRUSTED_PROXY_CIDRS`); in production, auth rate limits fail closed with `HTTP 503` if Redis is unreachable rather than silently downgrading to per-process memory. `services/quotas.py` enforces atomic UTC-day per-user caps (`chat: 500`, `image_generation: 50`, `coding_task: 50`, `file_upload: 100`, `scheduled_job: 30`) inside `user_usage_quotas`.
3. **Backend Components:** `services/rate_limit.py`, `services/quotas.py`, `config/settings.py`.
4. **Frontend Components:** Quota status display in `components/app/AccountMenu.tsx` and graceful `429` error handling in `lib/api.ts`.
5. **Database Interactions:** `user_usage_quotas`.
6. **External Dependencies:** Redis 7 (production rate limits), PostgreSQL 15 (atomic quotas).
7. **Implementation Status:** **Implemented & Verified** (`test_fail_closed_security_regression.py` & `GET /api/v1/auth/me/quotas`).

---

## Module 14: Real-Time Event Hub & System Readiness Telemetry
1. **Purpose:** Deliver instant multi-worker task notifications to browsers and provide truthful operational health/capability introspection.
2. **Internal Workflow:** `realtime/manager.py` authenticates WebSocket upgrades via single-use database tickets (`POST /api/v1/auth/ws-ticket`), subscribes to per-user Redis Pub/Sub channels, and forwards worker progress events to connected tabs. `main.py` exposes `/health` (liveness) and `/readiness` (DB connection, Alembic head match `j9f7a263b56c`, Redis status, storage status, production secret guards), while `api/capabilities.py` exposes truthful runtime capability flags.
3. **Backend Components:** `realtime/manager.py`, `api/capabilities.py`, `main.py`.
4. **Frontend Components:** `hooks/useRealtime.ts`, `components/app/TopBar.tsx`, `components/PluginsView.tsx`.
5. **Database Interactions:** `websocket_tickets`, `alembic_version`.
6. **External Dependencies:** Redis 7 Pub/Sub (for cross-process WS fan-out).
7. **Implementation Status:** **Implemented & Verified**.
