# Sakura AI — Production, Operational & Legal Readiness Checklist

> **Document Status:** Pre-Launch Engineering & Operations Baseline  
> **Legal Disclaimer:** All legal policy sections (Privacy Policy and Terms of Service) require formal review and sign-off by qualified legal counsel prior to commercial or public launch. This document does not constitute legal advice or fabricated compliance certifications.

---

## 1. Privacy Policy *(Requires Human Legal Review)*

- Public draft route: `/privacy` ([privacy.tsx](frontend/pages/privacy.tsx))
- **Required legal review items before public launch:**
  - Exact legal entity name, registered address, and Data Protection Officer / privacy contact mailbox.
  - Subprocessor disclosure list (configured LLM providers such as Groq, OpenAI, Anthropic; object storage provider; SMTP provider; Pollinations image endpoint if enabled).
  - Jurisdictional rights disclosures (GDPR, CCPA/CPRA, etc.) matching target regions.
  - Confirmation of zero model-training agreements with upstream inference providers.

## 2. Terms of Service *(Requires Human Legal Review)*

- Public draft route: `/terms` ([terms.tsx](frontend/pages/terms.tsx))
- **Required legal review items before public launch:**
  - Governing law, dispute resolution, and limitation of liability clauses.
  - Acceptable Use Policy covering sandboxed code execution, AI-generated content, and rate limits.
  - Intellectual property ownership terms for user prompts, repository code, and generated media.

## 3. Support & Contact Channels

- Public contact page: `/contact` ([contact.tsx](frontend/pages/contact.tsx))
- Configure `NEXT_PUBLIC_SUPPORT_EMAIL` to a monitored support mailbox before deployment.
- Public issue tracker fallback: repository Issues URL (`https://github.com/Abhiram-C-Divakaran/Sakura-AI/issues`).
- Never hardcode unverified email addresses in UI or legal notices.

## 4. Account Deletion

- Users can delete individual conversations, memories, workspaces, and library files directly via the API/UI.
- Deleting a `User` row cascades to `conversations`, `messages`, `documents`, `document_chunks`, `projects`, `scheduled_tasks`, `background_tasks`, `user_integrations`, `repository_workspaces`, `coding_tasks`, `coding_jobs`, `image_generation_jobs`, `websocket_tickets`, and `password_reset_tokens`.
- **Operational requirement before public launch:** Before deleting a user record, run `cleanup_orphaned_storage_objects(user_id, db)` (and flush `storage_deletion_outbox`) so physical S3/disk objects under `users/<user_id>/` and workspace directories under `/workspaces/<workspace_id>` are purged. Add a dedicated self-service account deletion endpoint (`DELETE /api/v1/auth/me`) if operating in GDPR/CCPA jurisdictions.

## 5. Data Retention

- **Database records:** Retained until explicitly deleted by the user or workspace administrator.
- **Ephemeral auth artifacts:**
  - `websocket_tickets`: 60-second TTL, single-use (`consumed_at` enforced atomically). Schedule periodic pruning of rows where `expires_at < NOW() - INTERVAL '1 day'`.
  - `password_reset_tokens`: 30-minute TTL, SHA-256 hashed, single-use. Schedule periodic pruning of expired rows.
  - `sandbox_network_authorizations`: 5-minute default TTL, single-use. Schedule periodic pruning of expired rows.
- **Storage deletion outbox (`storage_deletion_outbox`):** Audited retention of deletion attempts and errors; completed rows can be archived or pruned after 30–90 days per policy.

## 6. User Data Export

- Individual library files, generated images, and workspace diffs are downloadable via authenticated API endpoints.
- **Operational requirement before public launch:** Implement an asynchronous account export job (`GET/POST /api/v1/account/export`) producing a user-scoped JSON/ZIP bundle if subject to GDPR Article 20 portability requirements.

## 7. Backup & Recovery

- **PostgreSQL (`sakura_postgres`):**
  - Enable automated daily `pg_dump` (or managed snapshot + WAL Point-in-Time Recovery) with encrypted off-host storage.
  - Test full restore + `alembic upgrade head` on a clean database monthly.
- **Object Storage (`SAKURA_STORAGE_BACKEND=s3`):**
  - Enable bucket versioning and lifecycle rules on the configured S3/R2/MinIO bucket.
- **Redis (`sakura_redis`):**
  - Used for realtime pub/sub, immediate job dispatch hints, rate limits, and capability nonce replay protection (all durable job state lives in PostgreSQL). Enable AOF persistence (`appendonly yes`) so active capability nonces survive brief restarts.

## 8. HTTPS & Reverse Proxy Requirements

- Production deployments MUST terminate TLS 1.2+ at a reverse proxy (Nginx, Caddy, Envoy, or cloud load balancer) in front of `frontend` (`:3000`) and `backend-api` (`:8000`).
- Proxy configuration requirements:
  - Forward `X-Forwarded-For`, `X-Forwarded-Proto: https`, and `Host`.
  - Enable HTTP/1.1 WebSocket upgrade (`Upgrade` / `Connection` headers) on `/api/v1/ws`.
  - Disable response buffering (`proxy_buffering off`) on SSE endpoints (`/api/v1/chat/stream`, `/api/v1/coding/.../events/stream`).
  - Set `NEXT_PUBLIC_SITE_URL` to the canonical `https://` origin and `CORS_ALLOWED_ORIGINS` strictly to trusted origins (never `*`).
  - Keep `postgres` (`5432`), `redis` (`6379`), and `sandbox-executor` (`9000`) strictly on the internal private network with zero public exposure.

## 9. Secrets Management

- Never commit `.env` files or production secrets into Git. Inject secrets at runtime via your infrastructure's secret manager (Vault, AWS/GCP Secret Manager, Docker Secrets, or Kubernetes Secrets).
- Mandatory independent production secrets (enforced by `Settings.validate_production_guards()` and `/readiness`):
  - `POSTGRES_PASSWORD`
  - `JWT_SECRET` (>= 32 high-entropy characters)
  - `INTEGRATION_ENCRYPTION_KEY` (>= 32 chars, independent of `JWT_SECRET`)
  - `SAKURA_SANDBOX_SERVICE_TOKEN` (shared only between `backend-api`, `coding-worker`, and `sandbox-executor`)
  - `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY` (>= 32 chars, independent of `JWT_SECRET`, `INTEGRATION_ENCRYPTION_KEY`, and `SAKURA_SANDBOX_SERVICE_TOKEN`)
- Optional feature secrets (features fail closed or report `NOT_CONFIGURED` when absent):
  - LLM providers: `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or local `OLLAMA_BASE_URL` + `OLLAMA_MODEL`
  - Storage: `SAKURA_STORAGE_BUCKET`, `SAKURA_STORAGE_ENDPOINT`, `SAKURA_STORAGE_ACCESS_KEY`, `SAKURA_STORAGE_SECRET_KEY`
  - Password reset email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `PUBLIC_APP_URL`

## 10. Rate Limiting

- Sliding-window rate limiting (`services/rate_limit.py`, Redis-backed with in-memory fallback) is active on:
  - `POST /api/v1/auth/register` (15 req / 15 min per IP)
  - `POST /api/v1/auth/token` (30 req / 15 min per IP; 15 req / 15 min per IP+username)
  - `POST /api/v1/auth/password-reset/request` (10 req / 15 min per IP; 5 req / 15 min per identifier)
  - `POST /api/v1/auth/password-reset/confirm` (15 req / 15 min per IP)
- Complement application limits with edge/reverse-proxy rate limits (`limit_req_zone` / WAF) on `/api/v1/chat/stream`, `/api/v1/images/jobs`, and `/api/v1/coding/*`.

## 11. Usage Quotas

- Enforce upload size caps (50 MB streaming spool limit in `services/upload.py`), sandbox CPU/RAM/PID/timeout/output hard caps (`SAKURA_SANDBOX_CPUS`, `SAKURA_SANDBOX_MEMORY_MB`, `SAKURA_SANDBOX_PIDS`, `SAKURA_HARD_OUTPUT_LIMIT_BYTES`), and bounded retry limits across `coding_jobs`, `image_generation_jobs`, `background_tasks`, and `storage_deletion_outbox`.
- **Pre-launch operator action:** Configure upstream LLM provider spend caps/alerts and per-user daily token/job quotas before opening self-serve signups.

## 12. Monitoring & Alerting

- **Liveness:** `GET /health` (backend-api `:8000`, sandbox-executor `:9000`).
- **Readiness:** `GET /readiness` (returns HTTP 200 `READY` only when PostgreSQL, Alembic head revision, Redis, secrets, independent capability key, storage backend, and remote sandbox executor + runtime image are all healthy; returns HTTP 503 `NOT_READY` otherwise, without leaking secret values).
- **Recommended alerts:**
  - `/readiness` non-200 for > 2 consecutive probes.
  - `coding_jobs` or `image_generation_jobs` stuck in `QUEUED` > 5 minutes (worker down).
  - `storage_deletion_outbox` rows in `FAILED` state > 0.
  - Elevated HTTP 401/403/429/5xx rates or sandbox capability rejection spikes.
  - Host disk usage on PostgreSQL, workspace volume, and Docker image cache > 80%.

## 13. Incident Response

1. **Detection & Triage:** Correlate via `X-Request-ID` response headers, structured worker logs, and `/readiness` payload.
2. **Containment:**
   - Suspected credential leak: rotate `JWT_SECRET` (invalidates all sessions), `INTEGRATION_ENCRYPTION_KEY`, `SAKURA_SANDBOX_SERVICE_TOKEN`, and `SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY` immediately.
   - Suspected sandbox abuse: cancel active jobs via `/api/v1/coding/tasks/{task_id}/cancel` (triggers `/executions/{execution_id}/cancel` container kill), isolate `sandbox-executor`, and inspect `coding_task_events` / `tool_executions`.
3. **Recovery & Postmortem:** Restore from verified snapshots if data corruption occurred, run `alembic current` + `/readiness`, document root cause and regression tests before closing.

## 14. Exact Infrastructure Deployment Requirements (`docker-compose.prod.yml`)

- Linux host (or container orchestrator) with Docker Engine and Docker Compose v2.
- Shared persistent volumes: `postgres_data`, `redis_data`, `sakura_workspaces` (mounted by `backend-api`, `worker`, `coding-worker`, and `sandbox-executor`), and S3-compatible object storage (AWS S3, Cloudflare R2, or MinIO).
- Build order enforced by Compose: `migration` runs `alembic upgrade head` -> `sandbox-runtime` builds `sakura-sandbox:<tag>` -> `sandbox-executor` verifies `/readiness` -> `backend-api`, `worker`, `coding-worker`, `scheduler`, and `frontend` start with healthcheck dependencies.
- Never run `SAKURA_EMBEDDED_CODING_WORKER=true` or `SAKURA_EMBEDDED_SCHEDULER=true` in production; run the dedicated `coding-worker`, `worker`, and `scheduler` services.
