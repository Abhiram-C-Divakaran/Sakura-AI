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

## 12. GitHub Branch Protection & Repository Governance *(Manual Repository Setting)*

> **Current Status:** `main` branch protection is **NOT YET ENABLED** (must be configured manually by a repository administrator in GitHub Settings → Branches → Branch protection rules for `main`).

Required settings before staging/production release:
- Require a pull request before merging (`>= 1` approving review; dismiss stale reviews on new commits).
- Require status checks to pass before merging (strict — branch must be up to date):
  - `Backend Tests & Schema Verification`
  - `Frontend Typecheck & Build`
  - `Docker Sandbox E2E Integration`
- Block force pushes and branch deletions on `main`.
- Require linear history or signed commits per organizational policy.
- Dedicated `image-worker` service (`python -m media.image_worker`) runs independently from `worker` (`SAKURA_WORKER_HANDLE_IMAGES=false`) in `docker-compose.prod.yml` so long-running background tasks cannot starve image generation or storage deletion maintenance.

