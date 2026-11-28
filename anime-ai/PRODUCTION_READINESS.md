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

> **Verified Status (GitHub API):** `main` branch protection is **ENABLED (`protected=true`)** with:
> - `required_pull_request_reviews`: `required_approving_review_count = 1`, `dismiss_stale_reviews = true`
> - `required_status_checks`: `strict = true` (branch must be up to date) requiring all 4 checks:
>   - `Backend Tests & Schema Verification`
>   - `Frontend Typecheck & Build`
>   - `Docker Sandbox E2E Integration`
>   - `Full-Stack Integration Tests`
> - `allow_force_pushes = false`, `allow_deletions = false`
> - **Optional Governance Hardening (currently `false`):** `enforce_admins = false`, `required_signatures = false`, `required_linear_history = false`, `required_conversation_resolution = false`. Enable `enforce_admins` before opening production/multi-maintainer operations so repository administrators cannot bypass PR checks.

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

## 14. Evidence-Based Release Readiness Assessment *(PR #1 Hardening Status)*

> **Truthfulness Policy:** Nothing below claims live production deployment, external cloud provisioning, or live third-party integration success without direct test/CI evidence. Items requiring external infrastructure or manual sign-off remain explicitly open.

### A. Implemented and Locally Verified
- **Python static compilation (`python -m compileall -q .`):** Exit `0` across `anime-ai/backend`.
- **Docker Compose production configuration validation (`docker compose -f docker-compose.prod.yml config -q`):** Exit `0` with Docker Compose `v5.6.0`.
- **Backend unit & cross-dialect contract test suite (`python -m unittest discover -s tests -p "test_*.py" -v`):** All non-PG/non-Docker tests pass locally (0 failures; PostgreSQL-only and Docker-daemon E2E tests are explicitly gated by `SAKURA_POSTGRES_TEST=1` / `SAKURA_SANDBOX_E2E=1` because Docker Desktop daemon, PostgreSQL 15, and Redis 7 are not running on the local Windows workstation).
- **Subprocess hardening regression suite (`tests/test_subprocess_hardening_regression.py`):** Verified locally — bounded concurrent stdout/stderr pipe draining (>128 KiB without deadlock), child+grandchild process-tree termination on timeout and asyncio cancellation, non-zero exit rejection even when stdout prints `{"ok": true}`, malformed/empty stdin and stdout rejection, production `test_delay_seconds` guard, and expired-lease cancellation fencing (`stale`).
- **Fail-closed security regression suite (`tests/test_fail_closed_security_regression.py`):** Verified locally — production `Settings.validate_production_guards()` and `get_capability_signing_key()` secret enforcement, `/readiness` 503 on missing production sandbox secrets, production Redis-unavailable fail-closed rate limiting (503) and nonce store denial, capability replay/scope/workspace/command mismatch denial, cross-user resource denial, invalid `SAKURA_SANDBOX_RUNTIME` denial, unresolved Docker volume denial on `/clone` and `/execute`, and production remote runtime connection/credential fail-closed errors.
- **Image variation & coding quota idempotency suites (`tests/test_image_variation_idempotency_regression.py`, `tests/test_postgres_pgvector_and_concurrency.py`):** Verified locally — repeated/concurrent duplicate requests, long (>112-char) prefix-sharing key non-collision, >128-char key rejection (HTTP 400), cross-user key isolation, conflicting payload rejection (HTTP 409, zero extra quota), retry after partial quota/Redis failures, atomic coding task quota reservation under concurrent idempotent replays, and unexpired-lease fencing across outbox, image, and coding workers.
- **Frontend static checks & production build (`npm ci`, `npm run typecheck`, `npm run lint`, `npm run build`):** Verified locally with exit `0` (0 TypeScript errors, 0 ESLint errors, all 12 Next.js routes compiled).

### B. Implemented and GitHub CI Verified *(Sakura AI CI)*
All four required GitHub Actions CI workflows execute on every PR #1 head commit with real containerized Linux infrastructure (zero silent skips on PG and Docker E2E suites):
1. **`Backend Tests & Schema Verification`:** Real PostgreSQL 15 + `pgvector` (`pgvector/pgvector:pg15`) and Redis 7 (`redis:7-alpine`): `alembic upgrade head`, `test_schema_parity.py`, `test_scheduler_resilience.py`, `test_postgres_pgvector_and_concurrency.py` (all PG concurrency, lease-fencing, rollback, duplicate-event, and pgvector migration/downgrade tests with 0 skips), official `postgres:15` `backup_postgres.sh` / `verify_restore.sh` positive & negative (tampered/corrupt dump) checks, `docker-compose.prod.yml config`, backend Docker image build, and full backend test suite.
2. **`Frontend Typecheck & Build`:** `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build`, Playwright Chromium browser E2E (`npm run test:e2e`), and production frontend Docker image build.
3. **`Docker Sandbox E2E Integration`:** Builds `sakura-sandbox`, `sakura-sandbox-executor`, and `sakura-backend` images; runs real PG 15 + Redis + remote Docker `sandbox-executor` + separate `coding.job_worker` container; executes `test_sandbox_e2e_docker.py`, `test_workspace_topology_e2e.py`, and `test_production_remote_coding_e2e.py` (0 skips) and asserts 0 orphaned `sakura-exec-*` / `sakura-smoke-*` containers.
4. **`Full-Stack Integration Tests`:** Runs PG 15 + Redis + remote Docker `sandbox-executor` + FastAPI API + 3 separate worker containers (`tasks.worker`, `media.image_worker`, `coding.job_worker`) + Next.js frontend and executes Playwright `npm run test:e2e:fullstack` plus 0 orphaned container check.

### C. Implemented but Not Verified Against Live External Services
- **S3-compatible object storage (`services/storage.py`):** Streaming uploads/downloads, bounded delete timeouts, and redacted `/readiness` probes are implemented and unit-tested, but NOT integration-tested against a live AWS S3 / Cloudflare R2 / MinIO bucket.
- **Live LLM & embedding providers (`OpenAI`, `Anthropic`, `Groq`, `Ollama`):** Implemented and verified via deterministic test providers and unit tests; live external provider quotas, latency, and embedding ingestion are not exercised in CI.
- **Transactional SMTP password reset delivery (`services/email.py`):** Implemented with fail-closed HTTPS `PUBLIC_APP_URL` enforcement; live external SMTP server authentication and deliverability (SPF/DKIM/DMARC) are not exercised in CI.
- **Nginx reverse proxy & TLS (`ops/nginx.conf.example`):** Template authored for TLS 1.2/1.3, WebSocket `/api/v1/ws`, and unbuffered SSE; not live-tested against a provisioned domain and certificate.

### D. Requires External Infrastructure
- **PostgreSQL 15 + `pgvector`:** Managed or dedicated PG 15 host with `pgvector` package available on private network.
- **Redis 7 with persistence:** Private-network Redis 7 configured with AOF (`--appendonly yes --appendfsync everysec`) and `noeviction` memory policy for rate-limit and capability replay nonces.
- **S3-compatible object storage:** Provisioned bucket with SSE, versioning, lifecycle rules, and scoped IAM credentials (`SAKURA_STORAGE_BACKEND=s3`).
- **Live LLM & embedding provider credentials:** Production keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, or private `OLLAMA_BASE_URL`).
- **SMTP & password reset delivery:** Configured transactional SMTP relay and canonical HTTPS `PUBLIC_APP_URL`.
- **Domain, DNS & TLS:** Public domain, TLS 1.2/1.3 certificates, deployed Nginx/LB reverse proxy, explicit `TRUSTED_PROXY_CIDRS`, `CORS_ALLOWED_ORIGINS`, and `NEXT_PUBLIC_SITE_URL`.
- **Monitoring & alerting:** External metrics/log/alert stack monitoring `/health`, `/readiness`, queue depths, `storage_deletion_outbox` `FAILED` count, HTTP 401/403/429/503 spikes, and disk utilization.
- **Backup automation & off-host restore drills:** Scheduled cron/runner executing `ops/scripts/backup_postgres.sh` to encrypted off-host storage and recurring staging `ops/scripts/verify_restore.sh` drills.

### E. Requires Manual Security, Legal, or Operational Approval
- **Sandbox host isolation:** Dedicated VM/host or rootless/gVisor runtime for `sandbox-executor`, plus host egress firewall blocking cloud metadata (`169.254.169.254`) and internal database subnets.
- **Secret rotation & vaulting:** Inject all secrets via secret manager (never `.env` in Git) and exercise rotation runbook (Section 4).
- **Multi-replica worker load verification:** Multi-replica staging load test verifying PostgreSQL `FOR UPDATE SKIP LOCKED`, Redis pub/sub fanout, and quota atomicity under sustained concurrency.
- **Branch protection admin enforcement:** Consider enabling `enforce_admins=true` on `main` prior to production launch (branch protection is already enabled with 4 required CI checks + 1 PR approval).
- **Privacy, Terms & Support contact:** Configure `NEXT_PUBLIC_SUPPORT_EMAIL` for `/contact` and obtain formal legal counsel sign-off on `/privacy` and `/terms`.

### Component-by-Component Readiness Matrix

| Component | Code & Tests | CI Verified | Live Staging/Prod Status |
| --- | --- | --- | --- |
| PostgreSQL 15 + `pgvector` | Implemented & hardened | Yes (`pgvector/pgvector:pg15`, 0 skips) | Requires external staging/prod PG 15 instance |
| Redis 7 (AOF persistence) | Implemented & fail-closed | Yes (`redis:7-alpine`) | Requires external staging/prod Redis 7 with AOF |
| S3-compatible object storage | Implemented + unit tested | Not live-S3 tested (CI uses local volume) | Requires provisioned bucket + staging S3 roundtrip test |
| Live LLM & embedding credentials | Implemented + deterministic test provider | Deterministic CI only | Requires live staging/prod API keys + smoke check |
| SMTP & password reset delivery | Implemented + fail-closed HTTPS checks | Unit tests only | Requires live SMTP credentials + staging email test |
| Domain & TLS | Runbook + env validator | Not live-tested | Requires DNS + TLS 1.2/1.3 cert provisioning |
| Nginx reverse proxy | Template (`ops/nginx.conf.example`) | Not live-tested | Requires staging proxy deploy + WS/SSE verification |
| Monitoring & alerting | `/health`, `/readiness`, outbox/queue counters | Endpoint probes tested | Requires external scraper/alert rules |
| Backup automation | `backup_postgres.sh` (version-checked + SHA-256) | Verified in `postgres:15` CI container | Requires scheduled off-host execution |
| Restore verification | `verify_restore.sh` (pos + tamper/corrupt neg) | Verified in `postgres:15` CI container | Requires recurring staging restore drill |
| Multi-replica worker reliability | Unified lease-expiry fencing + `SKIP LOCKED` | Verified in PG & 3-worker full-stack CI | Requires multi-replica staging load test |
| Sandbox host isolation | Non-root child, `--network none`, signed caps | Verified in Docker Sandbox E2E CI | Requires hardened host/VM + egress firewall (`169.254.169.254`) |
| Secret rotation | Startup + `/readiness` guards + runbook | Guard tests verified | Requires Vault/Secrets Manager + dry-run rotation |
| Privacy & Terms review | Pre-launch drafts mounted at `/privacy`, `/terms` | Browser smoke tested | Requires formal legal counsel sign-off |
| Support contact configuration | `NEXT_PUBLIC_SUPPORT_EMAIL` wired on `/contact` | Build tested | Requires production support address configured |

---

## 15. Controlled Private Staging Deployment Checklist

> **Staging Verdict:** Ready for **controlled private staging deployment** once PR #1 is merged and the infrastructure steps below are completed. **Not yet approved for public/commercial launch** until live external integrations, security/legal sign-off, and staging restore/load drills pass.

1. **Infrastructure provisioning:** Provision private-network PostgreSQL 15 (`pgvector` installed), Redis 7 (`--appendonly yes --appendfsync everysec`), S3-compatible bucket (SSE + versioning), and isolated host/VM for `sandbox-executor`.
2. **Environment & secret validation:** Populate independent high-entropy secrets in secret store (`POSTGRES_PASSWORD`, `JWT_SECRET`, `INTEGRATION_ENCRYPTION_KEY`, `SAKURA_SANDBOX_SERVICE_TOKEN`, `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY`), set `ENVIRONMENT=production`, `SAKURA_EMBEDDED_*=false`, `TRUSTED_PROXY_CIDRS`, `CORS_ALLOWED_ORIGINS`, `PUBLIC_APP_URL`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPPORT_EMAIL`, and run `python anime-ai/ops/scripts/validate_env.py` (must exit `0`).
3. **Backup before deployment:** On any non-empty database, run `ops/scripts/backup_postgres.sh` using a `postgres:15` client and verify the `.dump` + `.sha256` sidecar exist off-host.
4. **Database migrations:** Run `docker compose -f docker-compose.prod.yml run --rm migration` (`alembic upgrade head`) and confirm `alembic current` matches head and `document_chunks.embedding` is `vector(1536)`.
5. **Docker image build:** Build all 4 production images cleanly: `docker compose -f docker-compose.prod.yml build` (`backend`, `frontend`, `sandbox-runtime`, `sandbox-executor`).
6. **Sandbox executor isolation:** Start `sandbox-executor` on its isolated host/network, verify host firewall blocks `169.254.169.254` and DB subnets, and confirm `GET http://sandbox-executor:9000/readiness` returns HTTP 200 with `ready=true`, `non_root_execution=true`, `service_token_configured=true`, `capability_signing_key_configured=true`.
7. **API and worker startup:** Start `worker`, `image-worker`, `coding-worker`, `scheduler`, and `backend-api` (bound to `127.0.0.1:8000`).
8. **Frontend startup:** Start `frontend` (bound to `127.0.0.1:3000`) with canonical `NEXT_PUBLIC_SITE_URL`.
9. **TLS and reverse proxy:** Deploy Nginx/LB per `ops/nginx.conf.example` with TLS 1.2/1.3, WebSocket `/api/v1/ws` upgrade, unbuffered SSE (`proxy_buffering off`), and block public access to `/readiness`.
10. **Readiness and health checks:** Verify internal `GET http://127.0.0.1:8000/readiness` returns HTTP 200 `status=READY` (including S3 storage probe, Redis, PG 15 migration head, and sandbox executor).
11. **Monitoring and alerting:** Enable probes and alerts for `/health`, `/readiness`, queue depths (`sakura:tasks:queue`, `sakura:coding:jobs`, `sakura:image:jobs`), `storage_deletion_outbox` `FAILED > 0`, HTTP 401/403/429/503 spikes, and `/workspaces` disk >75%.
12. **Backup and restore verification:** Execute an end-to-end `backup_postgres.sh` + `verify_restore.sh` (`REQUIRE_CHECKSUM=true`, `REQUIRE_PGVECTOR=true`, `REQUIRE_RESTORED_VECTOR=true`) drill against a staging scratch DB and schedule daily backups.
13. **Staging UAT:** Execute manual end-to-end UAT (desktop + mobile): registration/login, SMTP password reset, chat streaming + live LLM, Library upload/RAG indexing/async deletion on S3, image generation/quotas, scheduled tasks, Sakura Code remote sandbox TDD loop, data export, and self-service account deletion.
14. **Load testing:** Run multi-replica concurrency test on staging verifying worker `SKIP LOCKED` claims, lease renewal under load, rate limiting, WebSocket pub/sub, and zero orphaned sandbox containers (`sakura-exec-*`, `sakura-smoke-*`).



