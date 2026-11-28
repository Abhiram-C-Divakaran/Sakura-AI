# Sakura AI — 50 Project Viva Questions & Answers + Senior Interview Challenges

Every answer below is strictly grounded in Sakura AI's actual codebase (`anime-ai/backend`, `anime-ai/frontend`, `anime-ai/docker-compose.prod.yml`, and verified CI Run `46157049085`). Do not claim technologies Sakura AI does not use.

---

## Table of Contents
1. [Architecture Questions (Q1–Q5)](#1-architecture-questions-q1q5)
2. [Database & Schema Questions (Q6–Q10)](#2-database--schema-questions-q6q10)
3. [AI & Multi-Provider LLM Questions (Q11–Q15)](#3-ai--multi-provider-llm-questions-q11q15)
4. [RAG & Vector Search Questions (Q16–Q20)](#4-rag--vector-search-questions-q16q20)
5. [FastAPI & Next.js Questions (Q21–Q25)](#5-fastapi--nextjs-questions-q21q25)
6. [Redis & Background Processing Questions (Q26–Q30)](#6-redis--background-processing-questions-q26q30)
7. [Docker & Sandbox Security Questions (Q31–Q35)](#7-docker--sandbox-security-questions-q31q35)
8. [Authentication & Application Security Questions (Q36–Q40)](#8-authentication--application-security-questions-q36q40)
9. [Testing, CI & Reliability Questions (Q41–Q45)](#9-testing-ci--reliability-questions-q41q45)
10. [Engineering Trade-Offs & Limitations Questions (Q46–Q50)](#10-engineering-trade-offs--limitations-questions-q46q50)
11. [Bonus: Challenging Senior Technical Interview Questions (I1–I8)](#11-bonus-challenging-senior-technical-interview-questions-i1i8)

---

## 1. Architecture Questions (Q1–Q5)

**Q1. What problem does Sakura AI solve compared to a basic LLM chat app?**  
Sakura AI unifies conversational AI, per-user Hybrid RAG, multimodal image generation, voice transcription, scheduled tasks, and autonomous repository coding inside a single multi-tenant platform—while solving the systems engineering challenges basic wrappers ignore: database-authoritative durable workers, lease fencing, strict tenant isolation, outbox object-storage deletion, and non-root Docker sandbox isolation.

**Q2. Why did you split the backend into an API server plus four standalone worker services instead of using FastAPI `BackgroundTasks`?**  
FastAPI `BackgroundTasks` live in web-server memory and vanish on process restarts or deployments. Separating `worker`, `image-worker`, `coding-worker`, and `scheduler` isolates CPU/IO-heavy jobs from HTTP latency, allows independent horizontal scaling, and guarantees crash recovery because PostgreSQL holds authoritative job state.

**Q3. How many services exist in the production topology (`docker-compose.prod.yml`) and what are their roles?**  
Ten logical components: Nginx TLS proxy (`nginx.conf.example`), Next.js frontend (`:3000`), FastAPI backend (`:8000`), `worker`, `image-worker`, `coding-worker`, `scheduler`, remote `sandbox-executor` (`:9000`), PostgreSQL 15 with `pgvector`, and Redis 7 (AOF + `noeviction`).

**Q4. How does the system know whether a deployment is healthy versus actually ready to receive traffic?**  
`GET /health` is a lightweight liveness probe confirming the Python process responds. `GET /readiness` performs deep checks: live DB connectivity, exact match between DB `alembic_version` and packaged Alembic head (`j9f7a263b56c`), Redis status, storage backend configuration, and production security secret guards.

**Q5. How is request traceability handled across the backend?**  
`add_correlation_and_latency` middleware in `main.py` reads or generates a UUID `X-Request-ID`, attaches it to `request.state.request_id`, echoes it in every response header, and records latency samples into a bounded 50-entry buffer.

---

## 2. Database & Schema Questions (Q6–Q10)

**Q6. How many database tables exist in Sakura AI, and how are they managed?**  
Exactly **32 SQLAlchemy ORM tables** defined in `database/models.py`, managed through **11 sequential Alembic migrations** (`8936a43c2fb5` through `j9f7a263b56c`). In production, `Base.metadata.create_all()` is disabled so schema changes happen strictly via Alembic.

**Q7. Why did you choose PostgreSQL with `pgvector` over a standalone vector database like Pinecone or Qdrant?**  
Storing `document_chunks.embedding` (`vector(1536)`) directly in PostgreSQL keeps document metadata, `user_id` ownership, `deletion_status`, and vector chunks inside a single ACID transaction. When a user deletes a document or account, chunks cascade atomically with zero cross-database synchronization drift.

**Q8. How does the codebase support both local SQLite development and PostgreSQL 15 `pgvector` production without diverging schemas?**  
In `database/models.py`, `Vector(1536)` uses `_PgVector(1536).with_variant(JSON(), "sqlite")`. On PostgreSQL it compiles to native `vector(1536)`; on SQLite it transparently uses `JSON()`. `test_schema_parity.py` verifies structural parity across all 32 tables in both environments.

**Q9. Why does `account_audit_events` NOT have a cascading foreign key to `users.id`?**  
When a user deletes their account via `DELETE /api/v1/auth/me`, the `users` row and all owned resources cascade-delete. Storing `subject_user_id` without a cascading FK preserves an immutable compliance/audit record of the deletion event.

**Q10. How do you guarantee database backups actually restore cleanly?**  
`ops/scripts/backup_postgres.sh` produces custom-format `pg_dump` archives with SHA-256 checksums, and `ops/scripts/verify_restore.sh` validates the checksum and restores into an isolated database. GitHub Actions CI runs both a positive restore test and a negative tampered-`.sha256` rejection test using the official `postgres:15` client.

---

## 3. AI & Multi-Provider LLM Questions (Q11–Q15)

**Q11. Which LLM providers are supported and how does `LLMRouter` choose among them?**  
`llm/router.py` supports **Groq**, **OpenAI**, **Anthropic**, and local **Ollama** (plus a strictly gated `DeterministicTestProvider` allowed only in `ENVIRONMENT=test`). `get_ordered_providers(intent)` orders providers by intent—for example, prioritizing `groq -> anthropic -> openai -> ollama` for coding and `anthropic -> openai -> groq -> ollama` for deep reasoning.

**Q12. How does provider failover avoid hiding configuration mistakes?**  
`is_transient_error()` classifies errors: transient failures (`429`, `500`/`502`/`503`/`504`, timeouts, network resets) trigger failover to the next configured provider, whereas non-retryable auth errors (`401`, `403`, invalid API key) fail transparently without silently switching or returning mock text.

**Q13. How does Sakura AI enforce privacy for sensitive prompts?**  
For intents in `PRIVATE_INTENTS = {"local_private", "private_data"}`, `LLMRouter` restricts the provider list exclusively to `["ollama"]`. If Ollama is not configured, it raises `PrivateModelUnavailableError` and fails closed—never leaking private prompts to OpenAI, Groq, or Anthropic.

**Q14. How do you prevent slow upstream AI providers from hanging backend workers?**  
All provider adapters and `EmbeddingManager` enforce bounded timeouts (e.g., `EMBEDDING_TIMEOUT_SECONDS=30.0` and bounded stream/HTTP timeouts), verified by regression tests in `test_fail_closed_security_regression.py`.

**Q15. How is conversational memory implemented?**  
Short-term context loads recent turns from `messages` for the owned conversation; long-term personal facts/preferences are persisted in `user_memories` via `memory/manager.py` and exposed for user inspection and deletion via `GET /api/v1/memory` and `DELETE /api/v1/memory/{id}`.

---

## 4. RAG & Vector Search Questions (Q16–Q20)

**Q16. Why use Hybrid RAG (`pgvector` + Okapi BM25) instead of dense vector search alone?**  
Dense embeddings excel at semantic paraphrases ("how do we stop double claims?") but struggle with exact identifiers ("`j9f7a263b56c`", "`HTTP 409`", "`for update skip locked`"). Combining dense cosine similarity with Okapi BM25 lexical scoring (`k1=1.5`, `b=0.75`) via Reciprocal Rank Fusion (RRF) captures both semantic meaning and exact keyword precision.

**Q17. How does Reciprocal Rank Fusion (RRF) combine dense and lexical scores?**  
Instead of naively adding uncalibrated raw cosine and BM25 scores, RRF ranks each candidate chunk independently in both lists and computes $\text{RRF}(d) = \sum_i \frac{1}{k + \text{rank}_i(d)}$, producing robust rank fusion without scale sensitivity.

**Q18. How are uploaded documents parsed and chunked?**  
`rag/ingestion/parser.py` uses `pdfplumber` for PDFs and UTF-8 extraction for Markdown, TXT, and source files, splitting text into overlapping windows of **800 characters** with **150-character overlap** so sentences spanning chunk boundaries preserve context.

**Q19. What happens to RAG if `OPENAI_API_KEY` is not configured?**  
`EmbeddingManager` strictly refuses to generate fake or random mock vectors. It stores `embedding = NULL`, `/api/v1/capabilities` truthfully reports dense embeddings unavailable, and `rag/retrieval.py` seamlessly executes Okapi BM25 lexical search over the user's chunks.

**Q20. How do you prevent a slow re-indexing job from writing stale chunks or resurrecting a deleted document?**  
Each `documents` row tracks an integer `index_generation` and `deletion_status`. Before writing chunks, the worker verifies that `documents.index_generation` still matches the job's generation and `deletion_status == 'ACTIVE'`; stale writes are discarded cleanly.

---

## 5. FastAPI & Next.js Questions (Q21–Q25)

**Q21. Why FastAPI over Flask or Django for this backend?**  
FastAPI natively supports `async`/`await` for SSE chat streaming, WebSockets, and non-blocking HTTPX calls to LLM APIs and `sandbox-executor`, while Pydantic v2 enforces strict request/response validation and auto-generates `/docs` OpenAPI specs.

**Q22. How does the Next.js frontend avoid CORS issues and protect API tokens?**  
In local dev and proxied setups, `next.config.js` rewrites `/api/*` to `SAKURA_API_PROXY_TARGET` (and Nginx routes `/api/*` in production). All authenticated calls flow through `authFetch` in `frontend/lib/api.ts`, attaching `Authorization: Bearer <token>` in headers only.

**Q23. How does the frontend render private images and PDF previews without putting JWTs in `<img src="...?token=">`?**  
`AuthenticatedImage.tsx` and `FilePreviewModal.tsx` fetch binary data using `authFetch` (Bearer header), convert the response to a browser `Blob`, and bind an ephemeral `URL.createObjectURL(blob)`—revoking it on unmount. The backend actively rejects `?token=` downloads with `HTTP 401`.

**Q24. Why did you add `images: { unoptimized: true }` to `next.config.js` in Phase 1?**  
`npm audit --omit=dev` flagged `/_next/image` advisories on `next@14.2.35`. Because Sakura AI does not rely on Next.js's built-in image optimizer (private images load via `AuthenticatedImage` Blobs), disabling `/_next/image` immediately eliminated that attack surface (verified returning `HTTP 404` live) while keeping PR #1 free of a breaking Next 16 + React 19 migration.

**Q25. How do real-time updates reach the React UI without polling every second?**  
`hooks/useRealtime.ts` fetches a single-use ticket (`POST /api/v1/auth/ws-ticket`) and opens a WebSocket to `/api/v1/ws?ticket=...`, receiving instant Redis Pub/Sub broadcasts from workers. Coding jobs also stream structured step events over SSE via `hooks/useCodingTaskStream.ts` with `after_sequence` catch-up replay.

---

## 6. Redis & Background Processing Questions (Q26–Q30)

**Q26. What are all the roles Redis 7 plays in Sakura AI?**  
Four distinct roles: (1) sliding-window rate-limit counters, (2) low-latency worker wakeup notifications, (3) cross-process Pub/Sub fan-out for WebSocket notifications, and (4) atomic single-use nonce tracking for sandbox network capability tokens. It runs with AOF persistence and `noeviction`.

**Q27. If Redis restarts or flushes, are background jobs lost?**  
No. PostgreSQL—not Redis—is the authoritative job store (`background_tasks`, `image_generation_jobs`, `coding_jobs`, `storage_deletion_outbox`). Redis only accelerates wakeups; workers automatically fall back to PostgreSQL polling if Redis is unavailable.

**Q28. Explain lease fencing (`execution_attempt_id` / `claim_token` + `lease_expires_at`). Why is it necessary?**  
Suppose Worker A claims a job, pauses due to GC or network partition, and its lease expires. Worker B legitimately reclaims the job with a new `execution_attempt_id`. When Worker A wakes up and tries to write `COMPLETED`, its conditional `UPDATE ... WHERE id=? AND execution_attempt_id=? AND lease_expires_at > NOW()` affects 0 rows, preventing split-brain corruption.

**Q29. How does `StorageDeletionOutbox` handle slow or hung S3 object deletions?**  
Deleting a document marks `deletion_status='DELETING'`, enqueues an outbox row, and returns `HTTP 202` immediately. The worker executes each deletion inside a bounded, killable subprocess (`services/storage_delete_runner.py`). If an S3 call hangs past its deadline, the subprocess is terminated cleanly and retried with backoff rather than deadlocking the worker.

**Q30. How does the cron scheduler prevent duplicate task runs across multiple instances or restarts?**  
`tasks/scheduler.py` evaluates cron expressions in each task's IANA timezone and inserts into `scheduled_task_runs` with a database unique constraint on `(task_id, scheduled_for)`. Even if two schedulers tick simultaneously, only one wins the insert.

---

## 7. Docker & Sandbox Security Questions (Q31–Q35)

**Q31. Why shouldn't the FastAPI API or `coding-worker` mount `/var/run/docker.sock` directly?**  
Anyone with Docker socket access can effectively gain root on the host. Isolating `/var/run/docker.sock` exclusively inside a dedicated `sandbox-executor` service (`coding/sandbox_service.py`) ensures that even a compromise of the web API or coding worker does not yield raw Docker daemon control.

**Q32. What exact kernel and container restrictions protect child coding containers?**  
Every container runs with `--rm`, `--user 1001:1001` (non-root), `--network none` (default), `--cap-drop ALL`, `--security-opt no-new-privileges:true`, `--cpus=2.0`, `--memory=512m`, `--pids-limit=64`, an allowlisted child environment (zero backend secrets), and a single bind mount of only the target workspace to `/workspace:rw`.

**Q33. How are sibling user workspaces protected from path traversal or symlink attacks?**  
`coding/security.py` (`WorkspaceSecurity`) validates strict UUID workspace IDs, resolves canonical `os.path.realpath`, rejects paths escaping the workspace root, and Docker mounts strictly `/workspaces/<workspace_uuid>:/workspace:rw` so sibling directories do not even exist inside the container filesystem.

**Q34. How does a coding task safely install packages if `--network none` is the default?**  
Networked execution (`--network bridge`) is blocked by default (`HTTP 403`). It requires an explicit user network authorization (`sandbox_network_authorizations`) that mints a short-lived HMAC-SHA256 capability token bound to `workspace_id`, exact command hash, scope, and expiry. `sandbox-executor` verifies the HMAC and atomically consumes the nonce once in Redis (failing closed if Redis is down).

**Q35. How do you prevent runaway infinite loops or leaked containers?**  
Commands enforce strict timeouts and bounded output caps (`100,000` chars). On timeout or user cancellation, the runtime executes `docker kill` followed by `docker rm -f`. Both Docker CI jobs explicitly assert **0 orphaned `sakura-exec-*` containers** after completion.

---

## 8. Authentication & Application Security Questions (Q36–Q40)

**Q36. Why did you migrate from `python-jose` to `PyJWT` in Phase 1?**  
`python-jose` is effectively unmaintained and carried historical dependency/security risks while `pyjwt[crypto]` was already present in `requirements.txt`. Migrating `auth/manager.py` to `PyJWT` (`HS256`) simplified the dependency tree and was verified by a dedicated tamper-rejection regression test and full CI.

**Q37. Why are WebSockets authenticated with single-use tickets instead of JWT query parameters?**  
Browsers cannot easily attach custom `Authorization` headers to native `WebSocket` handshakes, and putting a long-lived JWT in `?token=` leaks it into reverse-proxy logs and browser history. Instead, the client calls `POST /api/v1/auth/ws-ticket` with a Bearer header to receive a 60-second opaque single-use ticket stored in `websocket_tickets` and consumed atomically on first use.

**Q38. What happens if an attacker sends another user's conversation or document UUID?**  
All tenant queries filter by both resource UUID and `current_user.id` (`auth/authorization.py`). Cross-tenant lookups return `HTTP 404 Not Found` (avoiding existence enumeration), and malformed UUIDs return `HTTP 400 Bad Request`.

**Q39. Why do authentication rate limits return `HTTP 503` when Redis is down in production?**  
Falling back silently to per-process in-memory counters across multiple API replicas weakens brute-force protection unpredictably. Failing closed (`503`) on auth endpoints guarantees consistent security policy enforcement, while `TRUSTED_PROXY_CIDRS` prevents clients from spoofing `X-Forwarded-For` headers.

**Q40. How does `POST /api/v1/tasks` stop malicious users from forging internal system jobs like `storage_delete`?**  
`api/routes.py` validates every request against `ALLOWED_USER_TASK_TYPES = frozenset({'code_analysis', 'dataset_analysis', 'doc_summary', 'web_research'})`. Any internal or unrecognized task type is rejected immediately with `HTTP 400`.

---

## 9. Testing, CI & Reliability Questions (Q41–Q45)

**Q41. How many automated tests exist and what was actually verified?**  
Locally, `unittest discover` runs **271 backend tests** (`253` passed, `18` environment-gated skipped on SQLite, `0` failed), plus `tsc --noEmit`, `next lint`, `next build`, and **37/37 live full-stack API/UI checks**. On GitHub Actions (Run `46157049085` on `d8de865`), **all 4 required CI jobs passed**—including PostgreSQL 15 + `pgvector` with **0 skips**, backup/restore verification, real Docker sandbox E2E, and unmocked Playwright browser E2E.

**Q42. How does image variation idempotency handle duplicate clicks vs. conflicting payloads?**  
Clients send an `Idempotency-Key`. `image_variation_batches` stores both `(user_id, idempotency_key)` and a canonical `request_fingerprint`. Replaying the exact same request returns the existing batch (`HTTP 202`), whereas reusing the same key with different parameters is rejected with `HTTP 409 Conflict`.

**Q43. What does `test_schema_parity.py` verify and why is it valuable?**  
It compares every table, column, type, nullability, primary key, foreign key, and index produced by Alembic migrations against SQLAlchemy `Base.metadata` across all 32 tables—catching migration omissions before they ever reach production.

**Q44. Why are branch protection rules enabled on `main`?**  
`main` enforces 1 approving review, dismissal of stale reviews, strict up-to-date status on all 4 CI checks, no force pushes, and no deletions—enforcing disciplined release governance rather than direct pushes to `main`.

**Q45. Why did 18 backend tests skip locally on Windows while passing in CI?**  
Those 18 tests explicitly require a live PostgreSQL 15 `pgvector` server (`DATABASE_URL=postgresql://...`) or an active Docker Engine + remote executor (`SAKURA_SANDBOX_E2E=1`). Local Windows had Docker Desktop stopped, whereas Ubuntu GitHub Actions runs all 18 tests with **0 skips**.

---

## 10. Engineering Trade-Offs & Limitations Questions (Q46–Q50)

**Q46. Why keep SQLite support if production requires PostgreSQL 15?**  
Supporting SQLite for local development lowers contributor and evaluator onboarding time to under 5 minutes without requiring Docker or PostgreSQL installation, while dialect-aware ORM types and mandatory PostgreSQL 15 CI prevent SQLite from masking PostgreSQL bugs.

**Q47. Why not upgrade Next.js 14 to Next.js 16 immediately during Phase 1?**  
Upgrading from `next@14.2.35` (React 18) to `next@16` (React 19) is a major breaking framework migration that would bloat a security/stability PR with high regression risk. Disabling `/_next/image` mitigated the active advisory immediately while isolating the Next 16 upgrade into a dedicated follow-up PR.

**Q48. Why do Google Drive, Notion, Slack, and Jira connectors return `HTTP 501` instead of mock UI success?**  
Truthfulness is a core design invariant in Sakura AI: `/api/v1/capabilities`, `/readiness`, and `api/integrations.py` never fake operational status. GitHub is genuinely implemented with encrypted token storage and live API validation; unimplemented providers honestly return `501 Not Implemented`.

**Q49. Why does image editing/variation use prompt-context regeneration instead of pixel-level inpainting?**  
The integrated Pollinations raster pipeline accepts text/seed/dimension parameters rather than binary mask tensors. Sakura AI tracks parent-child lineage (`parent_image_id`, `lineage_depth`) for conversational refinement and truthfully reports `image_conditioned_edit: false` and `true_upscale: false` in `/api/v1/capabilities`.

**Q50. What is the single biggest operational gap remaining before opening Sakura AI to public internet users?**  
Provisioning a real external staging/production infrastructure (hardened separate `sandbox-executor` host or microVM runtime, TLS certificates, managed PostgreSQL 15 + Redis 7 + S3 + SMTP, live load testing, and completing the Next.js 16 upgrade and formal legal review of `/privacy` and `/terms`).

---

## 11. Bonus: Challenging Senior Technical Interview Questions (I1–I8)

**I1. Walk me through a split-brain failure mode in your worker architecture and prove how your SQL prevents it.**  
If Worker A stalls for 90s on a 60s lease, recovery transitions the job back to `QUEUED` and Worker B claims it with a new `execution_attempt_id`. Worker A's final `UPDATE coding_jobs SET status='COMPLETED' WHERE id=:id AND execution_attempt_id=:a_id AND lease_expires_at > NOW()` matches 0 rows because both `execution_attempt_id` and `lease_expires_at` fail the predicate—even if Worker A tries to commit *before* recovery runs, `lease_expires_at > NOW()` still fences it out!

**I2. How does your coding sandbox resist container escape and SSRF against cloud instance metadata (`169.254.169.254`)?**  
Default `--network none` completely removes network interfaces (zero SSRF). Even on an explicitly authorized `--network bridge` command, non-root `1001:1001`, `--cap-drop ALL`, and `no-new-privileges:true` block privileged syscalls; for public multi-tenant cloud deployment, `sandbox-executor` is designed to sit on an isolated host/VM with IMDSv2 hop-limit=1 or firewall egress rules blocking `169.254.169.254`.

**I3. At 10 million document chunks, what becomes the bottleneck in your current `pgvector` + BM25 Hybrid RAG?**  
Two bottlenecks: (1) exact sequential `pgvector` scans would need an HNSW index (`m=16`, `ef_construction=64`) partitioned or filtered cleanly per tenant, and (2) Python-side Okapi BM25 over all a user's chunks should shift to PostgreSQL native `tsvector` + GIN indexes (`ts_rank_cd`) so both dense and lexical top-K candidate retrieval execute inside PostgreSQL before RRF fusion.

**I4. Why use `FOR UPDATE SKIP LOCKED` instead of Redis Streams or Celery?**  
Because job rows already need relational foreign keys (`user_id`, `workspace_id`, `document_id`), transactional visibility with API writes (outbox pattern!), and SQL-level lease fencing. `FOR UPDATE SKIP LOCKED` eliminates dual-write inconsistency between PostgreSQL and an external broker while Redis still delivers instant wakeups.

**I5. How do you ensure `DELETE /api/v1/auth/me` doesn't leave orphaned S3 objects if S3 is temporarily down during account deletion?**  
Before removing user metadata, `services/account.py` cancels active jobs, collects all owned `storage_key`s across documents, images, and exports, reconciles or enqueues durable purge records, and records an immutable `account_audit_events` entry so failed object deletions are trackable and recoverable.

**I6. Why is `TRUSTED_PROXY_CIDRS` critical when running FastAPI behind Nginx?**  
If a rate limiter blindly trusts the leftmost IP in `X-Forwarded-For`, an attacker can send `X-Forwarded-For: <random-ip>` on every login attempt and bypass brute-force limits completely. Parsing `X-Forwarded-For` right-to-left while stripping only peers inside `TRUSTED_PROXY_CIDRS` extracts the real client IP unforgeably.

**I7. What happens if two users send the same `Idempotency-Key`?**  
Idempotency uniqueness is scoped to `(user_id, idempotency_key)`, so keys are completely isolated per tenant and cannot collide or leak across users.

**I8. How did you verify that your test suite isn't just passing on mocks?**  
In `.github/workflows/ci.yml`, `Backend Tests & Schema Verification` runs against real `pgvector/pgvector:pg15` and `redis:7`, `Docker Sandbox E2E Integration` builds and executes real non-root Docker containers via `sandbox-executor`, and `Full-Stack Integration Tests` runs unmocked Playwright Chromium against all 3 separate workers + API + Next.js with zero skipped assertions.
