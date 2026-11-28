# Sakura AI — Production, Operational & Legal Readiness Package

> **Document Status:** Staging & Production Operations Baseline  
> **Legal Disclaimer:** Public policy drafts (`/privacy`, `/terms`) require formal review and sign-off by qualified legal counsel before public/commercial launch. This package provides technical operations runbooks, not legal advice.

---

## 1. Operational Artifacts Included

| Artifact | Purpose |
| --- | --- |
| [`ops/nginx.conf.example`](ops/nginx.conf.example) | TLS 1.2/1.3 reverse proxy, WebSocket `/api/v1/ws` upgrade, SSE `proxy_buffering off`, internal-only `/readiness` |
| [`ops/scripts/validate_env.py`](ops/scripts/validate_env.py) | Pre-flight environment validator (secrets, driver consistency, `TRUSTED_PROXY_CIDRS`, `PUBLIC_APP_URL`, storage) |
| [`ops/scripts/backup_postgres.sh`](ops/scripts/backup_postgres.sh) | Compressed custom-format `pg_dump` with SHA-256 checksum and retention pruning |
| [`ops/scripts/verify_restore.sh`](ops/scripts/verify_restore.sh) | Automated restore verification into a temporary database with Alembic head & table verification |
| [`docker-compose.prod.yml`](docker-compose.prod.yml) | Production service topology (PostgreSQL+pgvector, Redis AOF, migration, sandbox runtime/executor, API, workers, scheduler, frontend) |

---

## 2. Reverse Proxy, TLS, WebSocket & SSE Requirements

- Terminate TLS 1.2/1.3 at a reverse proxy (see [`ops/nginx.conf.example`](ops/nginx.conf.example)).
- `docker-compose.prod.yml` binds `backend-api` (`127.0.0.1:8000`) and `frontend` (`127.0.0.1:3000`) strictly to loopback by default so direct unencrypted public traffic cannot bypass the proxy.
- **WebSocket (`/api/v1/ws`):** Requires HTTP/1.1 `Upgrade` and `Connection: upgrade` headers and long read/send timeouts (`3600s`). Auth uses short-lived single-use tickets (`POST /api/v1/auth/ws-ticket`) — query-string JWT tokens are forbidden.
- **SSE streaming (`/api/v1/chat/stream`, `/api/v1/coding/tasks/*/events/stream`):** MUST set `proxy_buffering off`, `proxy_cache off`, `X-Accel-Buffering no`, and `proxy_read_timeout 3600s`.
- **Private Network Boundaries:** `postgres` (`5432`), `redis` (`6379`), and `sandbox-executor` (`9000`) MUST remain exclusively on the private Docker/VPC network with zero public exposure.

---

## 3. Trusted Proxies & Canonical Public URL

- **`TRUSTED_PROXY_CIDRS`:** Comma-separated CIDRs of your reverse proxy/load balancer (e.g., `127.0.0.1/32,10.0.0.0/8,172.16.0.0/12`). `services/rate_limit.py` ignores `X-Forwarded-For` unless `request.client.host` falls inside a configured trusted CIDR, and walks forwarded hops right-to-left to defeat header spoofing.
- **`PUBLIC_APP_URL`:** Canonical `https://` origin (non-localhost) used to generate password reset links. In production, password reset fails closed (`503`) if `PUBLIC_APP_URL` is missing, non-HTTPS, or points to `localhost`.
- **`NEXT_PUBLIC_SITE_URL` / `CORS_ALLOWED_ORIGINS`:** Must match your canonical `https://` origin (never `*` in production).

---

## 4. Environment Variable Checklist & Validation

Run `python anime-ai/ops/scripts/validate_env.py` against your deployment environment before starting services.

Mandatory production secrets (never committed to Git; inject via Vault / AWS Secrets Manager / GCP Secret Manager / Docker Secrets):
- `POSTGRES_PASSWORD` (>= 12 chars)
- `DATABASE_URL` (`postgresql+psycopg2://...`)
- `REDIS_URL` (`redis://...` or `rediss://...`)
- `JWT_SECRET` (>= 32 high-entropy chars)
- `INTEGRATION_ENCRYPTION_KEY` (>= 32 chars, independent of `JWT_SECRET`)
- `SAKURA_SANDBOX_SERVICE_TOKEN` (>= 24 chars, shared only by `backend-api`, `coding-worker`, and `sandbox-executor`)
- `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY` (>= 32 chars, independent of all other secrets)
- `SAKURA_STORAGE_BACKEND=s3` + `SAKURA_STORAGE_BUCKET`, `SAKURA_STORAGE_ACCESS_KEY`, `SAKURA_STORAGE_SECRET_KEY` (or single-node durable absolute `SAKURA_STORAGE_ROOT=/data/library`)
- `SAKURA_EMBEDDED_WORKER=false`, `SAKURA_EMBEDDED_SCHEDULER=false`, `SAKURA_EMBEDDED_CODING_WORKER=false`

Optional feature variables:
- LLM providers: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, or `OLLAMA_BASE_URL` + `OLLAMA_MODEL`
- Password reset SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `PUBLIC_APP_URL` (HTTPS)
- Daily per-user quotas: `SAKURA_QUOTA_CHAT_DAILY`, `SAKURA_QUOTA_IMAGE_DAILY`, `SAKURA_QUOTA_CODING_DAILY`, `SAKURA_QUOTA_UPLOAD_DAILY`, `SAKURA_QUOTA_SCHEDULED_DAILY`

**Secret Rotation Procedure:**
1. Rotate `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY` and `SAKURA_SANDBOX_SERVICE_TOKEN` together across `sandbox-executor`, `coding-worker`, and `backend-api` during a brief maintenance drain (in-flight capability tokens expire within 60–180s).
2. Rotate `JWT_SECRET` to invalidate all active user sessions (users re-authenticate cleanly).
3. Rotate `POSTGRES_PASSWORD` in PostgreSQL first, update secret store, and roll services.

---

## 5. Account Lifecycle, Data Export & Retention

- **Self-service Account Deletion (`DELETE /api/v1/auth/me`):** Requires explicit confirmation (`confirm: "DELETE"`) and current password verification. Atomically cancels queued/running coding, image, and background jobs; removes user workspace directories; purges user-owned storage objects under `users/<user_id>/` (with durable `storage_deletion_outbox` fallback on transient errors); removes DB records; and persists a non-sensitive `account_audit_events` row.
- **Async User Data Export (`POST /api/v1/auth/me/export`, `GET /api/v1/auth/me/export/{id}`, `GET /api/v1/auth/me/export/{id}/download`):** Durable worker job builds a user-isolated ZIP archive (`users/<user_id>/exports/<export_id>/sakura_export.zip`) containing profile (no password hashes), conversations, messages, memories, projects, documents metadata, images metadata, scheduled tasks, and coding tasks.
- **Retention Pruning:** Periodically prune expired rows in `websocket_tickets`, `password_reset_tokens`, and `sandbox_network_authorizations` older than 24 hours, and expired `user_data_exports` older than 7 days.

---

## 6. Rate Limiting & Durable Per-User Quotas

- **Auth Rate Limiting (`services/rate_limit.py`):** Redis-backed sliding window on `/auth/register`, `/auth/token`, `/auth/password-reset/request`, `/auth/password-reset/confirm`. Fails closed (`HTTP 503`) in production if Redis is unavailable on security-sensitive auth routes.
- **Per-User Daily Quotas (`services/quotas.py`, `user_usage_quotas` table):** Atomic multi-worker DB-backed UTC daily counters enforced on chat (`chat`), image generation (`image_generation`), Sakura Code tasks (`coding_task`), file uploads (`file_upload`), and scheduled jobs (`scheduled_job`). Inspectable via `GET /api/v1/auth/me/quotas`.

---

## 7. Backup, Restore & Storage Durability

- **PostgreSQL:** Schedule `ops/scripts/backup_postgres.sh` daily (plus WAL archiving / managed PITR where supported) and run `ops/scripts/verify_restore.sh <dump>` weekly/monthly against an isolated staging PostgreSQL instance.
- **Object Storage (`SAKURA_STORAGE_BACKEND=s3`):** Enable bucket versioning, server-side encryption, and lifecycle policies. Monitor `storage_deletion_outbox` rows where `status = 'FAILED'` (target: `0`).
- **Redis (`sakura_redis`):** Runs with `--appendonly yes --appendfsync everysec` in `docker-compose.prod.yml` so active capability replay nonces and rate-limit windows survive restarts. All authoritative job/task state remains in PostgreSQL.

---

## 8. Sandbox Executor Host Isolation & Workspace Disk Security

- **Docker Socket Isolation:** `sandbox-executor` is the **only** container permitted to mount `/var/run/docker.sock`. Neither `backend-api`, `worker`, `coding-worker`, nor child containers ever mount the Docker socket.
- **Host Isolation Policy:** For multi-tenant staging/production, deploy `sandbox-executor` on a dedicated hardened host/VM (or rootless Docker / gVisor / Firecracker runtime) isolated from database hosts and cloud instance metadata (`169.254.169.254` blocked via host egress firewall).
- **Child Container Hardening:** Every child runs non-root (`--user 1001:1001`), `--network none` by default (bridge only with single-use HMAC-signed `network_exec` or `repository_clone` capability validated against Redis), `--cap-drop ALL`, `--security-opt no-new-privileges:true`, CPU/RAM/PID caps, output byte caps, and single-workspace bind mounts (`/workspace` only, never parent `/workspaces`).
- **Workspace Disk Monitoring:** Alert when `sakura_workspaces` volume or Docker overlay storage exceeds 75% utilization; prune stale unused workspaces and dangling containers (`sakura-exec-*`, `sakura-smoke-*`).

---

## 9. Monitoring, Alerting & Queue Health

- **Health & Readiness Probes:**
  - `GET /health` (liveness on `:8000` and `:9000`)
  - `GET /readiness` (deep readiness checking PostgreSQL, Alembic head, Redis, secrets, independent signing key, storage backend, and remote sandbox executor + runtime image + non-root smoke test)
- **Worker & Queue Lag Alerts:**
  - `coding_jobs`, `image_generation_jobs`, or `background_tasks` remaining `QUEUED` > 5 minutes.
  - Redis list lengths (`LLEN sakura:tasks:queue`, `LLEN sakura:coding:jobs`, `LLEN sakura:image:jobs`) growing monotonically.
  - `storage_deletion_outbox` `FAILED` count > 0.
  - `/readiness` returning non-200 for > 2 consecutive intervals.
  - Spike in HTTP 401/403/429/503 responses or sandbox capability rejections.

---

## 10. Deployment, Migration Ordering & Rollback Runbook

### Deployment Order
1. Run `python anime-ai/ops/scripts/validate_env.py`.
2. Take a verified PostgreSQL backup (`ops/scripts/backup_postgres.sh`).
3. Build images: `docker compose -f docker-compose.prod.yml build`.
4. Run database migrations before starting app containers: `docker compose -f docker-compose.prod.yml run --rm migration` (verifies `alembic upgrade head`).
5. Start infrastructure & sandbox: `postgres`, `redis`, `sandbox-runtime`, `sandbox-executor` -> confirm `sandbox-executor` `/readiness` HTTP 200.
6. Start workers & scheduler: `worker`, `coding-worker`, `scheduler`.
7. Start `backend-api` -> confirm `GET http://127.0.0.1:8000/readiness` returns HTTP 200 `READY`.
8. Start `frontend` and reload reverse proxy.

### Incident & Rollback Procedure
1. **App-only regression (compatible schema):** Roll back container image tags and restart `backend-api`, `worker`, `coding-worker`, `scheduler`, `frontend`; verify `/readiness`.
2. **Schema rollback (only if last migration caused breakage):** Stop API & workers -> run `alembic downgrade -1` (or restore from pre-deploy `pg_dump` snapshot if destructive) -> start previous image tags -> verify `/readiness`.
3. **Credential compromise:** Rotate affected secrets immediately, restart affected services, audit `account_audit_events` and container logs.

---

## 11. Legal Policy Review Checklist *(Requires Human Legal Sign-Off)*

- `/privacy` (`frontend/pages/privacy.tsx`) and `/terms` (`frontend/pages/terms.tsx`) are explicitly labeled as pre-launch drafts requiring legal review before public release.
- Configure `NEXT_PUBLIC_SUPPORT_EMAIL` for `/contact` before staging/public launch.

---

## 12. GitHub Branch Protection & Repository Governance *(Verified Live on GitHub)*

> **Verified Status (GitHub API — `GET /repos/Abhiram-C-Divakaran/Sakura-AI/branches/main/protection`):** `main` branch protection is **ENABLED (`protected=true`)** with:
> - `required_pull_request_reviews`: `required_approving_review_count = 1`, `dismiss_stale_reviews = true`
> - `required_status_checks`: `strict = true` (branch must be up to date) requiring all 4 checks:
>   - `Backend Tests & Schema Verification`
>   - `Frontend Typecheck & Build`
>   - `Docker Sandbox E2E Integration`
>   - `Full-Stack Integration Tests`
> - `allow_force_pushes = false`, `allow_deletions = false`
> - **Optional Governance Hardening (currently `false`):** `enforce_admins = false`, `required_signatures = false`, `required_linear_history = false`, `required_conversation_resolution = false`. Enable `enforce_admins` before opening production/multi-maintainer operations so repository administrators cannot bypass PR checks.
> - **Main-vs-Hardening Discrepancy Resolution:** Prior to PR #1, `main:anime-ai/PRODUCTION_READINESS.md` recorded `protected=false` from before branch protection was configured on GitHub. Live GitHub API inspection confirms `protected=true` on `main`; merging PR #1 resolves that historical documentation discrepancy on `main`. PR #1 itself currently reports `reviewDecision: REVIEW_REQUIRED` (`reviews: []`) and requires an independent human approving review before merge.

Operational service isolation notes:
- Dedicated `image-worker` service (`python -m media.image_worker`) runs independently from `worker` (`SAKURA_WORKER_HANDLE_IMAGES=false`) in `docker-compose.prod.yml` so long-running background tasks cannot starve image generation or storage deletion maintenance.
- PostgreSQL backups (`ops/scripts/backup_postgres.sh`) and restore verifications (`ops/scripts/verify_restore.sh`) MUST run with a client whose major version matches the PostgreSQL server (e.g., official `postgres:15` container for PG 15); both scripts enforce major-version parity and `verify_restore.sh` requires the `.sha256` sidecar and fails non-zero if `alembic_version`, core tables, `pgvector` extension, `vector(1536)` column type, or restored data checks fail.

---

## 13. Manual Staging & Production Provisioning Checklist *(No Hosting Provider Assumed)*

The repository is deployment-neutral and has no confirmed hosting provider or public production deployment. Before opening private staging or public launch, an operator must manually provision and configure:
1. **Compute / Hosting:** Dedicated VM, container cluster, or isolated host(s) separating `sandbox-executor` from database/storage networks.
2. **PostgreSQL 15 + `pgvector`:** Managed or self-hosted PostgreSQL 15 instance with `pgvector` available (`alembic upgrade head` installs `CREATE EXTENSION IF NOT EXISTS vector` and `vector(1536)`).
3. **Redis 7 (AOF enabled):** Private-network Redis instance for rate limiting, WebSocket pub/sub, worker dispatch, and sandbox capability replay protection.
4. **S3-Compatible Object Storage:** Bucket with SSE, versioning, lifecycle rules, and scoped IAM credentials (`SAKURA_STORAGE_BACKEND=s3`).
5. **LLM & Embedding Credentials:** Production keys for desired providers (`OPENAI_API_KEY` for semantic embeddings / GPT, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, or private `OLLAMA_BASE_URL`). Never enable `SAKURA_DETERMINISTIC_TEST_PROVIDERS` outside `ENVIRONMENT=test`.
6. **SMTP Delivery:** Configured transactional SMTP credentials (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`) and canonical HTTPS `PUBLIC_APP_URL` for password recovery.
7. **Domain & TLS:** DNS records, TLS 1.2/1.3 certificates, reverse proxy (`ops/nginx.conf.example`), `TRUSTED_PROXY_CIDRS`, `CORS_ALLOWED_ORIGINS`, and `NEXT_PUBLIC_SITE_URL`.
8. **Monitoring & Alerts:** Health/readiness checks (`/health`, `/readiness`), queue depth, `storage_deletion_outbox` `FAILED` count, HTTP 429/503 spikes, and workspace disk utilization alerts.
9. **Backup Scheduling & Restore Drills:** Scheduled daily `backup_postgres.sh` uploads to off-host encrypted storage plus regular automated `verify_restore.sh` drills with `REQUIRE_CHECKSUM=true` and `REQUIRE_PGVECTOR=true`.
10. **Support & Legal Review:** Set `NEXT_PUBLIC_SUPPORT_EMAIL` for `/contact` and obtain formal legal counsel review/sign-off on `/privacy` and `/terms` before public launch.

### Pre-Public-Launch Gate (Beyond Private Staging)
- Independent security assessment / penetration review of auth, multi-tenant isolation, and sandbox egress controls.
- Load & concurrency testing against staging PostgreSQL, Redis, and worker replicas.
- Full end-to-end backup + restore drill into a clean staging PostgreSQL 15 instance (`verify_restore.sh` with `REQUIRE_CHECKSUM=true`, `REQUIRE_PGVECTOR=true`, `REQUIRE_RESTORED_VECTOR=true`).
- User acceptance testing (UAT) covering desktop & mobile chat, Library, Knowledge Base semantic RAG, image generation/quotas, scheduled tasks, Sakura Code, data export, and account deletion.

### Frontend Image Variation Entry-Point Note
- `GenerateImageModal.tsx` (`LibraryView.tsx`) generates and preserves a retry-stable `idempotency_key` via `createIdempotencyKey('img_gen')` for `POST /api/v1/library/generate-image`.
- `POST /api/v1/images/variation` enforces required `idempotency_key` (`HTTP 400`, max 128 chars, collision-safe child job keys), normalized request fingerprint replay (`HTTP 202`, zero extra quota, idempotent re-enqueue of still-`QUEUED` jobs), payload conflict rejection (`HTTP 409`), and legacy `NULL`-fingerprint compatibility validation on the backend. No mounted frontend UI button currently calls `/api/v1/images/variation` (`ImageLightboxModal.tsx` is unmounted), so no dead frontend client helper is shipped.

---

## 14. Evidence-Based Release Readiness Assessment *(PR #1 Release Candidate Status)*

> **Truthfulness Policy:** No live public deployment exists, no external hosting provider is assumed, and no unexecuted or infrastructure-blocked check is claimed as passed. Every capability below is classified strictly by direct verification evidence.

### 1. Implemented
- Unified lease-fenced `StorageDeletionOutbox` + async `HTTP 202` document deletion + killable isolated subprocess runner (`services/storage_delete_runner.py`, Win32/POSIX process-tree cleanup, bounded stdout/stderr pipe draining).
- Unexpired-lease fencing and per-row conditional CAS stale-job recovery across all four durable workers: `StorageDeletionOutbox`, `DurableTaskWorker` (`tasks/worker.py`, `tasks/task_manager.py`), `ImageJobWorker` (`media/image_worker.py`), and `CodingJobWorker` (`coding/job_worker.py`).
- PostgreSQL 15 + `pgvector` native `vector(1536)` Alembic migration (`j9f7a263b56c`) with strict historical JSON/vector validation, rollback/downgrade safety, and version-pinned backup/restore verification scripts (`ops/scripts/backup_postgres.sh`, `ops/scripts/verify_restore.sh`).
- Image variation idempotency (`HTTP 400` on missing/blank/>128-char keys, `HTTP 202` replay with zero extra quota, `HTTP 409` on payload mismatch, collision-safe child keys, legacy `NULL`-fingerprint compatibility) and atomic `coding_task` quota reservation across both `/api/v1/coding/workspaces/{id}/tasks` and `/api/v1/chat/stream`.
- Fail-closed production security guards (`config/settings.py`, `coding/capabilities.py`, `coding/sandbox.py`, `coding/sandbox_service.py` with kill-before-remove container cleanup fencing, `services/rate_limit.py`, `ops/scripts/validate_env.py` enforcing secret independence, non-wildcard `CORS_ALLOWED_ORIGINS`, and disabling `SAKURA_DETERMINISTIC_TEST_PROVIDERS`), strict scheduled-task cross-user ownership + `POST /api/v1/tasks` public task-type allowlist + manual scheduled-run quota enforcement (`tasks/task_manager.py`, `api/routes.py`, `api/scheduled.py`), bounded streaming audio upload & extension allowlist (`api/audio.py`), StorageBackend-aware S3 chat attachment loading (`llm/agent.py`), authenticated Blob-based Library image previews and file downloads (`frontend/components/AuthenticatedImage.tsx`, `LibraryView.tsx`, `FilePreviewModal.tsx`), non-root container sandbox isolation (`--user 1001:1001`, `--network none` default, `--cap-drop ALL`, single-workspace mount), `docker-compose.prod.yml` / `frontend/Dockerfile` Redis `--maxmemory-policy noeviction` and forwarding of `CORS_ALLOWED_ORIGINS`, `SAKURA_EMBEDDED_WORKER=false`, `NEXT_PUBLIC_SITE_URL`, and `NEXT_PUBLIC_SUPPORT_EMAIL`, and explicit account-deletion cleanup including `ImageVariationBatch` and prior `FAILED` outbox row reconciliation (`services/account.py`).

### 2. Locally Tested *(Windows Workstation — Python 3.14.3, Node v24.13.0, npm 11.19.0, Docker Compose v5.6.0)*
- **Python static compilation (`python -m compileall -q .`):** Passed (`exit 0`).
- **Docker Compose production configuration (`docker compose -f docker-compose.prod.yml config -q`):** Passed (`exit 0`).
- **Backend test suites (SQLite):** **248/248 full suite passed on `ddaf927`** (0 failures, 18 infrastructure-gated skips: 7 PG-only, 10 Docker Sandbox E2E, 1 local Docker daemon check) plus **22/22 targeted security & sandbox cleanup tests passed** (19/19 `test_fail_closed_security_regression.py` including `validate_env.py` and `cancel_execution` kill-before-remove ordering + 3/3 `test_sandbox_output_limits_and_cleanup.py`), including:
  - `tests/test_fail_closed_security_regression.py` (all passed)
  - `tests/test_image_variation_idempotency_regression.py` (all passed)
  - `tests/test_subprocess_hardening_regression.py` (all passed)
  - `tests/test_coding_verification_semantics.py` (all passed)
  - `tests/test_postgres_pgvector_and_concurrency.py` cross-dialect suite (`TestDatabaseContractAndHardening`, including `DurableTaskWorker` lease-resurrection fencing, CAS recovery, and account-deletion outbox/`ImageVariationBatch` cleanup — all passed).
- **Frontend verification (`anime-ai/frontend`):** `npm ci` (`exit 0`, 364 packages), `npm run typecheck` (`exit 0`, 0 errors), `npm run lint` (`exit 0`, 0 errors; non-blocking warnings only), and `npm run build` (`exit 0`, all 12 routes compiled).

### 3. GitHub CI Verified *(Sakura AI CI — Ubuntu Linux with Real PG 15, Redis 7, Docker & Playwright Chromium)*
All four required GitHub Actions workflows run on every PR #1 head commit with zero silent skips on PostgreSQL and Docker E2E suites:
1. **`Backend Tests & Schema Verification`:** Real PostgreSQL 15 + `pgvector` (`pgvector/pgvector:pg15`) and Redis 7 (`redis:7-alpine`): `alembic upgrade head`, `test_schema_parity.py`, `test_scheduler_resilience.py`, `test_postgres_pgvector_and_concurrency.py` (0 skips), official `postgres:15` `backup_postgres.sh` + `verify_restore.sh` (positive + tampered-checksum + corrupted-archive negative checks), `docker-compose.prod.yml config`, backend Docker image build, and full backend test suite.
2. **`Frontend Typecheck & Build`:** `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build`, Playwright Chromium browser E2E (`npm run test:e2e`, desktop + mobile), and production frontend Docker image build.
3. **`Docker Sandbox E2E Integration`:** Builds `sakura-sandbox`, `sakura-sandbox-executor`, and `sakura-backend` images; runs PG 15 + Redis + remote Docker `sandbox-executor` + separate `coding.job_worker` container; executes `test_sandbox_e2e_docker.py`, `test_workspace_topology_e2e.py`, and `test_production_remote_coding_e2e.py` (0 skips) and asserts 0 orphaned `sakura-exec-*` / `sakura-smoke-*` containers.
4. **`Full-Stack Integration Tests`:** Runs PG 15 + Redis + remote Docker `sandbox-executor` + FastAPI API + 3 separate worker containers (`tasks.worker`, `media.image_worker`, `coding.job_worker`) + Next.js frontend and executes unmocked Playwright `npm run test:e2e:fullstack` plus 0 orphaned container check.

### 4. Live Staging Tested
- **None.** No private staging environment has been provisioned or tested yet.

### 5. Not Tested
- Live S3-compatible object storage roundtrip (AWS S3 / Cloudflare R2 / MinIO upload, streaming download, signed URL, outbox deletion, SSE/versioning).
- Live third-party LLM & embedding provider calls (`OpenAI`, `Anthropic`, `Groq`, or live `Ollama`) under production rate limits and semantic RAG ingestion.
- Live transactional SMTP password-reset delivery and SPF/DKIM/DMARC deliverability.
- Live Nginx reverse proxy TLS 1.2/1.3 termination, `/api/v1/ws` WebSocket upgrade, unbuffered SSE streaming, and `/readiness` public block.
- Sustained multi-replica staging concurrency/load tests and manual desktop/mobile UAT.

### 6. Blocked by Missing Infrastructure
- **On Local Windows Workstation (cannot run locally; verified in GitHub Linux CI instead):**
  - Docker Desktop Linux Engine daemon is not running (`//./pipe/dockerDesktopLinuxEngine` unavailable) -> blocks local Docker image builds (`backend`, `frontend`, `sandbox-runtime`, `sandbox-executor`), local PostgreSQL 15 + `pgvector` tests (`psql` not installed locally), local Redis 7 integration (`redis-server` not installed locally), local remote Docker sandbox E2E, and local multi-process full-stack integration.
  - Playwright Chromium headless binary (`chromium_headless_shell-1255`) is not installed locally -> blocks local Playwright browser execution (executed in GitHub CI `Frontend Typecheck & Build` and `Full-Stack Integration Tests`).
- **For Private Staging & Public Launch:** Provisioning of hosting/isolated sandbox-executor host, PostgreSQL 15 + `pgvector`, Redis 7 (AOF), S3-compatible storage, live LLM/embedding credentials, SMTP relay, domain/DNS/TLS, secret manager, monitoring/alerting, and off-host backup storage.

### 7. Requires Human Approval
- **PR #1 Independent Approving Review:** Required by live `main` branch protection (`reviewDecision: REVIEW_REQUIRED`, `required_approving_review_count = 1`) before PR #1 can be merged into `main`.
- **Governance Decision (`enforce_admins`):** Repository owner decision to enable `enforce_admins=true` on `main` before multi-maintainer/public operations.
- **Security & Infrastructure Sign-Off:** Dedicated isolated host/VM and host egress firewall (`169.254.169.254` and DB subnets blocked) for `sandbox-executor`, plus secret-manager injection and rotation dry-run.
- **Legal & Support Sign-Off (Public Launch Gate):** Formal legal counsel review of `/privacy` and `/terms` pre-launch drafts and confirmation of production `NEXT_PUBLIC_SUPPORT_EMAIL` on `/contact`.
- **Explicit Deployment Authorization:** Human operator authorization for private staging deployment and later public launch.

### Component-by-Component Readiness Matrix

| Component | Implemented | Locally Tested (Windows) | GitHub CI Verified | Live Staging Tested | Remaining Gate |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL 15 + `pgvector` | Yes | Blocked (no local PG/Docker) | Yes (`pgvector/pgvector:pg15`, 0 skips) | No | Provision staging PG 15 + `pgvector` |
| Redis 7 (AOF persistence) | Yes | Blocked (no local Redis/Docker) | Yes (`redis:7-alpine`) | No | Provision staging Redis 7 (AOF + `noeviction`) |
| S3-compatible object storage | Yes | Unit tests only | Unit tests only (CI uses local vol) | No | Provision bucket (SSE + versioning) + staging roundtrip |
| Live LLM & embedding credentials | Yes | Deterministic/unit only | Deterministic CI only | No | Provision live API keys + staging smoke check |
| SMTP & password reset delivery | Yes | Fail-closed unit tests | Unit tests only | No | Provision SMTP relay + staging email test |
| Domain, DNS, TLS & Nginx proxy | Template + validator | `validate_env` unit tests | Not live-tested | No | Provision DNS/TLS + deploy proxy + WS/SSE verify |
| Secret manager & secret rotation | Guards + runbook | Guard regression suite | Guard regression suite | No | Inject via secret manager + dry-run rotation |
| Monitoring, alerting & queue health | `/health`, `/readiness` | Endpoint unit tests | Endpoint probes | No | Wire external scraper & alert rules |
| Backup & restore verification | `backup_postgres.sh`, `verify_restore.sh` | Blocked (no local Docker/PG) | Yes (`postgres:15`, pos + neg) | No | Schedule off-host backups + staging restore drill |
| Multi-worker concurrency & leases | Unified CAS + unexpired fencing | SQLite concurrency tests | PG `SKIP LOCKED` + 3-worker CI | No | Multi-replica staging load test |
| Sandbox host & container isolation | Remote HTTP + non-root + caps | Fail-closed + subprocess suites | Docker Sandbox E2E CI (0 skips) | No | Dedicated hardened host + egress firewall |
| Frontend build & browser E2E | Yes | `npm ci`, `typecheck`, `lint`, `build` (Playwright blocked locally) | Build + Playwright E2E + Full-Stack E2E | No | Desktop & mobile manual staging UAT |
| Privacy, Terms & Support contact | Pre-launch drafts mounted | Build verified | Browser smoke tested | No | Legal counsel sign-off + `NEXT_PUBLIC_SUPPORT_EMAIL` |
| GitHub `main` governance | Enabled (`protected=true`) | Verified via `gh api` | 4/4 required checks enforced | N/A | 1 human approving review on PR #1; optional `enforce_admins=true` |

---

## 15. Controlled Private Staging Deployment Checklist *(Deployment-Neutral)*

> **Staging Verdict:** Ready for **controlled private staging deployment** once PR #1 receives an independent approving review, is merged into `main`, and the 12 operator steps below are completed. **No public deployment exists and Sakura AI is not yet approved for public/commercial launch** until live external integrations, security/legal sign-off, and staging restore/load/UAT gates pass.

1. **Hosting & Isolated Sandbox-Executor Infrastructure:** Provision private-network compute separating `sandbox-executor` onto a dedicated hardened VM/host (or rootless Docker / gVisor runtime) with host egress firewall blocking cloud metadata (`169.254.169.254`) and database subnets; ensure only `sandbox-executor` mounts `/var/run/docker.sock` and verify `GET http://sandbox-executor:9000/readiness` returns HTTP 200 (`ready=true`, `non_root_execution=true`, `service_token_configured=true`, `capability_signing_key_configured=true`).
2. **PostgreSQL 15 with `pgvector`:** Provision private-network PostgreSQL 15 with `pgvector` available; run `docker compose -f docker-compose.prod.yml run --rm migration` (`alembic upgrade head`) and confirm `alembic current` matches head and `document_chunks.embedding` has type `vector(1536)`.
3. **Redis 7 with AOF Persistence:** Provision private-network Redis 7 with `--appendonly yes --appendfsync everysec` and `maxmemory-policy noeviction` so rate-limit windows and capability replay nonces survive restarts.
4. **S3-Compatible Object Storage (Encryption & Versioning):** Provision an S3-compatible bucket with server-side encryption (SSE), bucket versioning, and lifecycle rules; configure `SAKURA_STORAGE_BACKEND=s3` with scoped IAM credentials and verify upload/preview/async outbox deletion roundtrip.
5. **Production LLM & Embedding Credentials:** Inject live provider keys (`OPENAI_API_KEY` for embeddings/GPT, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, or private `OLLAMA_BASE_URL`), ensure `SAKURA_DETERMINISTIC_TEST_PROVIDERS` is unset/disabled, and verify real chat streaming + semantic RAG retrieval.
6. **SMTP & Password Reset Delivery:** Configure transactional SMTP credentials (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`) and canonical HTTPS `PUBLIC_APP_URL`; execute a real password-reset email delivery and confirmation test.
7. **Domain, DNS, TLS & Reverse Proxy:** Configure DNS records, TLS 1.2/1.3 certificates, and reverse proxy per `ops/nginx.conf.example` (HTTP/1.1 WebSocket upgrade on `/api/v1/ws`, `proxy_buffering off` on SSE routes, public access to `/readiness` blocked, loopback-only backend/frontend binds, explicit `TRUSTED_PROXY_CIDRS`, `CORS_ALLOWED_ORIGINS`, `NEXT_PUBLIC_SITE_URL`).
8. **Secret Manager & Secret Rotation:** Inject all independent high-entropy secrets (`POSTGRES_PASSWORD`, `JWT_SECRET`, `INTEGRATION_ENCRYPTION_KEY`, `SAKURA_SANDBOX_SERVICE_TOKEN`, `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY`) via secret manager (never `.env` in Git), run `python anime-ai/ops/scripts/validate_env.py` (must exit `0`), and dry-run the Section 4 rotation procedure.
9. **Monitoring, Alerting & Queue Health:** Wire external probes and alerts for `/health`, internal `/readiness` (HTTP 200 `READY`), queue lag (`sakura:tasks:queue`, `sakura:coding:jobs`, `sakura:image:jobs`), `storage_deletion_outbox` `FAILED > 0`, HTTP 401/403/429/503 spikes, and `/workspaces` disk >75%.
10. **Automated Off-Host Backups & Restore Drills:** Schedule daily `ops/scripts/backup_postgres.sh` (using a `postgres:15` client) with encrypted off-host upload and execute a clean staging restore drill via `ops/scripts/verify_restore.sh` (`REQUIRE_CHECKSUM=true`, `REQUIRE_PGVECTOR=true`, `REQUIRE_RESTORED_VECTOR=true`).
11. **Multi-Worker Concurrency & Load Tests:** Run staging multi-replica concurrency tests against `worker`, `image-worker`, `coding-worker`, and `backend-api` verifying PostgreSQL `FOR UPDATE SKIP LOCKED` claims, lease renewal/fencing, Redis pub/sub fanout, quota atomicity, and `0` orphaned sandbox containers (`sakura-exec-*`, `sakura-smoke-*`).
12. **Desktop & Mobile User Acceptance Testing (UAT):** Execute end-to-end manual UAT on desktop and mobile browsers covering registration/login, SMTP password reset, chat streaming + live LLM, Library upload/RAG indexing/async deletion on S3, image generation/variation idempotency/quotas, scheduled tasks, Sakura Code remote sandbox TDD workflow, async data export, and self-service account deletion.



