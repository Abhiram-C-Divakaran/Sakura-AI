# Sakura AI — Technical Interview Preparation Guide

> **Purpose:** Prepare to defend Sakura AI's architecture, engineering trade-offs, security controls, and distributed-systems design in software engineering interviews. Every explanation below maps directly to real code in this repository — nothing is fabricated.

---

## 1. Architecture & Technology Rationale

### Why This Architecture?
Sakura AI separates **synchronous user interaction** (FastAPI API + Next.js UI), **durable asynchronous execution** (PostgreSQL-backed workers + Redis wakeups), and **untrusted code execution** (isolated HTTP `sandbox-executor` service). This prevents slow LLM inference, image rendering, storage I/O, or user code execution from blocking API workers, losing state on restart, or exposing backend credentials.

### Why FastAPI + Next.js?
- **FastAPI (Python):** Native `async`/`await` for SSE streaming and WebSockets, Pydantic v2 schema validation, first-class Python AI/ML ecosystem (`openai`, `anthropic`, `pdfplumber`, `numpy`, `pgvector`, `sqlalchemy`), and automatic OpenAPI docs.
- **Next.js 14 + TypeScript:** File-based routing for public marketing/legal/share pages alongside an interactive authenticated workspace (`/chat`), strict compile-time typing (`tsc --noEmit`), and clean dev proxy rewrites (`SAKURA_API_PROXY_TARGET`).

### How PostgreSQL 15 and `pgvector` Work Together
- PostgreSQL is the **single authoritative source of truth** for users, conversations, documents, chunks, durable job queues, outbox rows, and daily quotas.
- `document_chunks.embedding` uses native `pgvector` type `vector(1536)` (migrated in `j9f7a263b56c_pgvector_embeddings_and_variation_fingerprint.py`). Storing relational metadata and vector embeddings in the same database gives **transactional consistency**: when a document is deleted or re-indexed, its chunks and vectors update atomically with zero dual-write drift against a separate vector store.
- On SQLite (local dev/unit tests), `HybridRetriever` transparently falls back to NumPy cosine similarity over JSON arrays while keeping identical API semantics.

### How Redis and Durable Background Workers Work Together
- **Database is authoritative; Redis is an accelerator and ephemeral security store.**
- Workers (`tasks.worker`, `media.image_worker`, `coding.job_worker`) persist jobs in PostgreSQL **before** pushing job IDs to Redis lists (`sakura:tasks:queue`, `sakura:image:jobs`, `sakura:coding:jobs`). If Redis restarts or drops a notification, workers still discover queued jobs via DB polling.
- Workers acquire leases using PostgreSQL `FOR UPDATE SKIP LOCKED` (with per-row conditional CAS fallback on SQLite), renew leases via heartbeats, and fence writes with `assert_owned_in_session()` + `execution_attempt_id` so a paused/stale worker cannot overwrite a job reclaimed by another worker.
- Redis runs with `--appendonly yes --appendfsync everysec --maxmemory-policy noeviction` because it also backs **sliding-window auth rate limits**, **WebSocket cross-worker Pub/Sub**, and **single-use sandbox capability nonces**.

### How Hybrid RAG Operates (`backend/rag/retrieval.py`)
1. Queries first filter strictly by `Document.user_id == user_id` and `is_knowledge_base == True`.
2. **Dense Semantic Path:** If `OPENAI_API_KEY` is configured, `EmbeddingManager` generates a 1536-dim embedding (`text-embedding-3-small`, 30s timeout, `max_retries=2`) and runs native `pgvector` `cosine_distance` (`<=>`). If unconfigured, it truthfully returns `None` (never fake random embeddings).
3. **Lexical Path:** `BM25Scorer` scores chunks using Okapi BM25 (`k1=1.5`, `b=0.75`) with Robertson–Spärck Jones IDF, preserving exact matches for error codes, identifiers, and acronyms.
4. **Fusion:** Both rankings merge via **Reciprocal Rank Fusion** ($\text{score}(d) = \sum_m \frac{1}{60 + \text{rank}_m(d)}$) and return cited chunks with filenames and page numbers.

### How the Sakura Coding Agent & Remote Docker Sandbox Work
- Submitting a coding task (`POST /api/v1/coding/workspaces/{id}/tasks` or `/code` in chat) atomically checks idempotency, enforces the daily `coding_task` quota, creates `CodingTask` + `CodingJob`, and returns immediately.
- A separate `coding-worker` process claims the job and runs `CodingAgent` across 21 structured tools (`read_file`, `apply_patch`, `run_tests`, `git_diff`, etc.), recording ordered `CodingTaskEvent` rows streamed via SSE (`after_sequence` replay survives browser reloads).
- In production, `SandboxManager.get_runtime()` **mandates** `RemoteHttpSandboxRuntime` (`SAKURA_SANDBOX_EXECUTOR_URL`) and **never** falls back to local host execution.
- `sandbox-executor` (`coding/sandbox_service.py`) is the **only** container mounting `/var/run/docker.sock`. Every command spawns an ephemeral container with:
  - `--user 1001:1001` (non-root), `--cap-drop ALL`, `--security-opt no-new-privileges:true`
  - `--network none` by default (bridge network requires a short-lived, single-use, HMAC-SHA256-signed capability token bound to `workspace_id`, `scope`, and exact command hash, verified against Redis)
  - `--cpus`, `--memory`, `--pids-limit`, single-workspace mount (`/workspace` only), allowlisted child environment (zero backend secrets), bounded streaming output drainer, and kill-before-remove cleanup.

### How Auth, Authorization, Quotas & Rate Limits Work
- **Auth:** `PyJWT` (`HS256`) + `pbkdf2_sha256` password hashing (`auth/manager.py`). Production startup refuses weak/default/reused secrets (`config/settings.py`).
- **No Tokens in URLs:** WebSockets authenticate via single-use hashed tickets (`POST /api/v1/auth/ws-ticket`); Library/conversation file previews and downloads use `authFetch` + `Blob` URLs (`AuthenticatedImage.tsx`) and reject `?token=` with `HTTP 401`.
- **Rate Limits (`services/rate_limit.py`):** Redis sliding window on auth routes; respects `X-Forwarded-For` **only** when `request.client.host` is inside explicit `TRUSTED_PROXY_CIDRS` (parsed right-to-left). Fails closed (`HTTP 503`) in production if Redis is unreachable.
- **Quotas (`services/quotas.py`):** Atomic DB-backed UTC-day counters in `user_usage_quotas` (`chat`, `image_generation`, `coding_task`, `file_upload`, `scheduled_job`), preventing concurrent double-spend across multiple workers.

### How Failures Are Handled
- **Storage Deletion Outbox (`services/documents.py`, `storage_delete_runner.py`):** `DELETE /api/v1/library/files/{id}` marks the document `DELETING` and writes a `StorageDeletionOutbox` row atomically, returning `HTTP 202`. Workers execute deletions inside a killable isolated subprocess with bounded pipe draining and Win32/POSIX process-tree cleanup; transient failures back off exponentially and retry; permanent failures surface `DELETE_FAILED` with a UI retry button.
- **Worker Crashes:** Unexpired-lease fencing prevents double execution while leases are valid; expired leases are reclaimed once via conditional CAS `UPDATE ... WHERE status='RUNNING' AND lease_expires_at < now`, incrementing retries until max retries quarantine the job as `FAILED`.
- **Provider Outages:** LLM/embedding clients enforce bounded timeouts (`60s` / `30s`, `max_retries=2`), Groq fails over across fallback models on `404`/deprecation, private Ollama mode refuses cloud fallback, and unconfigured SMTP/Whisper return truthful `HTTP 503`.

---

## 2. Biggest Engineering Challenges & Key Trade-Offs

1. **Outbox Concurrency & Hung Storage Clients:** Blocking synchronous `boto3`/filesystem deletes inside an async worker risked hanging the entire event loop. *Solution:* Isolated killable subprocess runner (`storage_delete_runner.py`) with bounded pipe reading and process-group termination + lease renewal. *Trade-off:* Slightly higher per-deletion spawn overhead in exchange for guaranteed timeout enforcement and zero hung workers.
2. **Container Orphan Race During Cancellation:** Real CI (`Full-Stack Integration Tests`) caught a `sakura-exec-*` container left in `Created` state when cancellation raced ahead of `docker run` container creation. *Solution:* Enforce strict `proc.kill() -> proc.wait() -> docker rm -f` ordering in `sandbox_service.py` and await `/code` task completion in E2E tests.
3. **PostgreSQL vs. SQLite Dialect Parity:** Supporting SQLite for zero-friction local dev while shipping native PostgreSQL `pgvector` (`vector(1536)`) and `FOR UPDATE SKIP LOCKED` in production required dialect-aware branches and a dedicated schema-parity test (`test_schema_parity.py`) run against real PostgreSQL 15 in CI.
4. **Bearer Auth vs. Browser `<img>` / `<a download>`:** Removing `?token=` query-string JWTs improved security (no tokens in Nginx logs) at the cost of breaking native `<img>` and `<a download>` tags. *Solution:* `AuthenticatedImage` component + `downloadAuthenticatedFile` helper using `authFetch` + `URL.createObjectURL` with strict `URL.revokeObjectURL` cleanup.

### Honest List of What Remains Incomplete
- Live staging infrastructure has not yet been provisioned (S3, live LLM keys, SMTP, TLS/Nginx, isolated `sandbox-executor` host).
- Frontend runs `next@14.2.35` (`images.unoptimized: true` mitigates `/_next/image` advisories, but a full Next.js 16 + React 19 upgrade PR is still required before public launch).
- Third-party connectors beyond GitHub return `501 Not Implemented`; `/privacy` and `/terms` await legal review; `cleanup_orphaned_storage_objects()` needs a minimum object-age grace window.

---

## 3. Realistic Technical Interview Questions & Model Answers

1. **Q: Why didn't you use Celery or a separate vector database like Pinecone?**  
   *A:* Keeping durable job state and `vector(1536)` embeddings inside PostgreSQL eliminated dual-write consistency bugs (e.g., deleting a document atomically removes its chunks/vectors; enqueuing a job and deducting quota happen in one ACID transaction). Redis acts strictly as a fast wakeup/pub-sub/nonce layer while PostgreSQL remains authoritative.
2. **Q: What happens if Worker A hangs mid-job, its lease expires, Worker B reclaims the job, and Worker A wakes up?**  
   *A:* Every worker attempt gets a unique `execution_attempt_id` and `lease_owner`. Before committing state mutations, workers call `assert_owned_in_session(db, lock=True)` and use conditional CAS updates (`WHERE id = :id AND lease_owner = :me AND execution_attempt_id = :attempt`). Worker A detects lease loss (`TaskLeaseLostError`) and performs zero writes.
3. **Q: How do you prevent a user from exhausting their daily image variation or coding quota via concurrent duplicate requests?**  
   *A:* Both endpoints require/accept an `idempotency_key` enforced by a unique DB constraint on `(user_id, idempotency_key)`. Inside the same DB transaction, we check for an existing batch/job first; identical replays return `HTTP 202` with zero extra quota deduction, conflicting payloads return `HTTP 409`, and only new jobs increment `user_usage_quotas`.
4. **Q: How did you prevent SSRF when users clone arbitrary Git repositories into Sakura Code?**  
   *A:* `WorkspaceSecurity.validate_repository_url()` rejects shell metacharacters, `file://`/`ext::`/`fd::` schemes, `localhost`, `169.254.169.254`, `metadata.google.internal`, `.local`/`.internal`, and private/loopback/link-local IP literals and DNS resolutions. Additionally, production deployment requires a host egress firewall on the dedicated `sandbox-executor` VM blocking cloud metadata and DB subnets.
5. **Q: Why is `sandbox-executor` a separate service instead of mounting `/var/run/docker.sock` into FastAPI?**  
   *A:* Mounting the Docker socket is root-equivalent on the host. Isolating it into a dedicated service (and dedicated VM in staging/prod) ensures that a vulnerability in the API, task worker, or image worker never grants Docker daemon access, and every execution request requires both `X-Sandbox-Token` and (for network ops) a single-use HMAC-signed capability bound to workspace and exact command hash.
6. **Q: Why did you choose Hybrid RAG (pgvector + BM25 + RRF) over pure vector search?**  
   *A:* Dense embeddings capture semantic paraphrases well but often miss exact symbols, UUIDs, error strings, and rare acronyms. Combining `pgvector` cosine distance with Okapi BM25 via Reciprocal Rank Fusion gives high recall across both semantic and exact queries — and degrades honestly to BM25 when embedding keys are unconfigured.
7. **Q: How does your `DELETE /api/v1/library/files/{id}` handle S3 outages without leaving inconsistent state?**  
   *A:* Deletion is two-phase: the API atomically marks the `Document` `DELETING`, creates a `StorageDeletionOutbox` row, and returns `HTTP 202`. The outbox worker deletes the S3 object in a killable subprocess; only once storage deletion succeeds does it remove the DB record and emit a WebSocket `library_update` event. If S3 is down, retries back off cleanly until recovery.
8. **Q: Why did you ban `?token=<jwt>` query strings on WebSockets and file downloads?**  
   *A:* Query strings appear in reverse-proxy access logs, CDN logs, browser history, and `Referer` headers. WebSockets now exchange a Bearer header for a 60-second single-use hashed ticket (`POST /api/v1/auth/ws-ticket`), and file previews/downloads fetch via `authFetch` (`Authorization: Bearer`) into temporary client-side `Blob` URLs revoked on unmount.
9. **Q: How do you defeat `X-Forwarded-For` IP spoofing on auth rate limits?**  
   *A:* `services/rate_limit.py` ignores `X-Forwarded-For` completely unless `request.client.host` matches an explicit CIDR in `TRUSTED_PROXY_CIDRS`, then walks forwarded hops right-to-left to extract the first untrusted client IP. In production, if Redis is unavailable, auth rate limits fail closed with `HTTP 503`.
10. **Q: How did you prevent a user from forging internal background jobs like `scheduled_run`?**  
    *A:* During our independent security audit we found `POST /api/v1/tasks` accepted arbitrary task types while `execute_scheduled_task_job()` lacked a `ScheduledTask.user_id == user_id` filter. We fixed both layers: `POST /api/v1/tasks` now allowlists only 4 user-submittable task types (`HTTP 400` otherwise), and `execute_scheduled_task_job()` enforces `ScheduledTask.user_id == user_id` and `ScheduledTaskRun.task_id == st_uuid` (defense-in-depth).
11. **Q: How do you guarantee PostgreSQL backups actually restore with `pgvector` intact?**  
    *A:* `backup_postgres.sh` and `verify_restore.sh` enforce exact PG client/server major-version parity (`postgres:15`), write and verify `.sha256` checksums, restore into a disposable DB with `--exit-on-error`, and assert `alembic_version`, 17 core tables, `pgvector` extension, `vector(1536)` column type, non-null restored 1536-dim vectors, and cosine `<=>` execution — tested in CI with both positive and tampered-checksum negative cases.
12. **Q: Why does Redis run with `AOF` and `--maxmemory-policy noeviction`?**  
    *A:* Because Redis stores active sandbox capability replay nonces and rate-limit windows. Under an `allkeys-lru` policy, memory pressure could silently evict a consumed nonce before its TTL expires, enabling capability replay. `noeviction` + AOF ensures security state is never silently dropped.
13. **Q: How do you handle browser reloads mid-coding-task without losing progress?**  
    *A:* Every coding phase and tool execution persists an incrementing `sequence_number` row in `coding_task_events`. When `/chat` reloads, it fetches persisted messages containing `metadata.coding_task_id`, reconnects to `/api/v1/coding/tasks/{id}/events/stream?after_sequence=N`, and replays missed events cleanly.
14. **Q: What happens if a user uploads a 2 GB file to `/api/v1/audio/transcribe` or `/api/v1/library/upload`?**  
    *A:* Both endpoints stream in 1 MB chunks rather than calling unbounded `await file.read()`. Documents cap at 50 MB and audio caps at 25 MB (Whisper's upstream limit), immediately aborting with `HTTP 413` and cleaning up temporary files. Audio filenames are sanitized with `os.path.basename` and checked against an explicit extension allowlist (`HTTP 400`).
15. **Q: What is the first thing you would harden before opening Sakura AI to public users?**  
    *A:* Four things: (1) upgrade Next.js 14 → 16 to resolve upstream `npm audit` advisories, (2) provision a dedicated hardened `sandbox-executor` host with host-level egress firewall blocking `169.254.169.254` and DB subnets, (3) run live staging acceptance + multi-replica load tests against real S3/PG/Redis/SMTP, and (4) obtain legal sign-off on `/privacy` and `/terms`.
