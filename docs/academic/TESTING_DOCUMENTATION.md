# Sakura AI — Testing Strategy, Execution Matrix & Verified Results

> Companion standalone document to Chapter 10 of [`PROJECT_REPORT.md`](PROJECT_REPORT.md). Every test result recorded below reflects an actual command executed during Phase 1 or verified in GitHub Actions CI Run `46157049085` on commit `d8de8651886de7f5abeec41262f07dc86bf78b93`. No result is fabricated or extrapolated.

---

## 1. Layered Testing Architecture

Sakura AI verifies correctness across eight testing layers:

1. **Static Compilation & Type Safety:** Python bytecode compilation (`python -m compileall -q . ../ops/scripts`), TypeScript strict check (`tsc --noEmit`), ESLint (`next lint`), Docker Compose schema check (`docker compose -f docker-compose.prod.yml config -q`), and production environment validator (`ops/scripts/validate_env.py`).
2. **Backend Unit & Security Regression Tests:** `unittest` suite across `anime-ai/backend/tests/` covering `PyJWT` auth, password complexity, fail-closed production guards, rate-limit Redis failure (`503`), IDOR isolation (`404`), malformed UUID rejection (`400`), header-only file downloads (`401` on `?token=`), forged internal task blocking (`400`), and provider/embedding timeouts.
3. **Database Schema Parity & Migration Tests:** Full Alembic `upgrade head` / `downgrade` validation and dialect-aware ORM-vs-database structural parity checks (`test_schema_parity.py`) across all 32 tables.
4. **PostgreSQL 15 Concurrency, `pgvector` & Backup/Restore Tests (CI):** Real `pgvector/pgvector:pg15` container verifying `vector(1536)` persistence/cosine retrieval, `FOR UPDATE SKIP LOCKED` multi-worker claims, outbox lease fencing, image variation idempotency (`400`/`202`/`409`), and official `postgres:15` `backup_postgres.sh` + `verify_restore.sh` (including negative test with tampered `.sha256` checksum).
5. **Background Worker & Outbox Fencing Tests:** Stale lease expiry recovery, conditional terminal-write rejection after lease loss, killable subprocess storage delete timeout/cleanup, and cancellation semantics (`test_coding_durable_jobs.py`, `test_worker_and_outbox_fencing.py`).
6. **Remote Docker Sandbox Isolation E2E Tests (CI):** Real `sakura-sandbox` + `sakura-sandbox-executor` + separate `coding-worker` containers verifying non-root `UID 1001:1001`, shared workspace ownership, `--network none` enforcement, HMAC single-use capability verification, and **0 orphaned `sakura-exec-*` containers**.
7. **Live Local Full-Stack API & Route Verification:** Automated 37-check HTTP journey script executed directly against running local FastAPI (`:8000`) and Next.js (`:3000`) servers.
8. **Full-Stack Browser E2E Tests (CI):** Unmocked Playwright Chromium tests running against the complete production-topology stack (PostgreSQL 15 + Redis 7 + Remote Docker Executor + FastAPI API + 3 separate workers + Next.js frontend).

---

## 2. Verified Testing Results Table

| Test ID | Layer | Test Case | Expected Result | Actual Observed Result | Environment | Status |
| --- | --- | --- | --- | --- | --- | --- |
| **TC-01** | Static / Python | `python -m compileall -q . ../ops/scripts` | Zero syntax or import compilation errors | Exited `0` with 0 syntax errors | Local + CI (`d8de865`) | **PASS** |
| **TC-02** | Unit / Security | Full backend `unittest discover` (`271` tests, incl. `test_auth_manager_uses_pyjwt_and_rejects_tampered_tokens`) | All non-gated unit, auth, quota, outbox, and security tests pass | `253` passed, `18` environment-gated skipped (PG/Docker flags), `0` failed | Local SQLite (`d8de865`) | **PASS** |
| **TC-03** | Database / Migrations | Alembic `upgrade head` + `test_schema_parity.py` on PostgreSQL 15 | All 11 migrations apply cleanly; 32 tables & `vector(1536)` match ORM | Applied to `j9f7a263b56c`; 32/32 tables match ORM (`0` diffs) | CI PG15 (`46157049085`) | **PASS** |
| **TC-04** | Database / Concurrency | `pgvector` cosine retrieval, `FOR UPDATE SKIP LOCKED`, outbox fencing, variation idempotency | Zero skips; concurrent workers never double-claim or overwrite after lease expiry | Passed with `0` skips and `0` failures | CI PG15 (`46157049085`) | **PASS** |
| **TC-05** | Ops / Disaster Recovery | `backup_postgres.sh` & `verify_restore.sh` (positive + tampered `.sha256` negative check) | Valid dump restores cleanly; tampered checksum fails closed | Both positive restore and negative tamper rejection passed | CI PG15 (`46157049085`) | **PASS** |
| **TC-06** | Frontend / Static | `npm run typecheck` (`tsc --noEmit`) & `npm run lint` (`next lint`) | 0 TypeScript errors; 0 ESLint errors | 0 TS errors; 0 ESLint errors (10 pre-existing non-blocking warnings) | Local + CI (`46157049085`) | **PASS** |
| **TC-07** | Frontend / Build | `npm run build` (`next build` with `images.unoptimized: true`) | Production bundle compiles cleanly | Compiled cleanly; `12/12` static pages generated; Docker image built in CI | Local + CI (`46157049085`) | **PASS** |
| **TC-08** | Live Local API & UI | 37-check live user-journey script (`live_journey_check.py`) against `:3000` & `:8000` | Pages `200`, `/_next/image` `404`, PyJWT login `200`, `?token=` `401`, cross-user `404`, forged task `400`, `DELETE /auth/me` `200` | `37/37` checks passed, `0` failed | Local Live Stack | **PASS** |
| **TC-09** | Sandbox E2E | Real Docker sandbox execution (`sakura-sandbox` + `sandbox-executor` + separate `coding-worker`) | Non-root `1001:1001`, `--network none`, capability enforcement, `0` orphaned containers | All assertions passed (`0` skips); `0` orphaned containers verified | CI Ubuntu (`46157049085`) | **PASS** |
| **TC-10** | Full-Stack E2E | Unmocked Playwright Chromium against PG15 + Redis + Executor + API + 3 Workers + Next.js | End-to-end browser journeys succeed with `0` orphaned sandbox containers | Job `Full-Stack Integration Tests` completed with `conclusion: success` | CI Ubuntu (`46157049085`) | **PASS** |
| **TC-11** | Dependency Audit | `npm audit --omit=dev` on `anime-ai/frontend` | Identify production npm vulnerabilities | Reported 3 advisories (`next@14.2.35`, `postcss`, `source-map-js`); `/_next/image` mitigated via `images.unoptimized: true`; Next 16 upgrade tracked for follow-up PR | Local Audit | **MITIGATED / TRACKED** |
| **TC-12** | Local Docker / PG | Running Docker sandbox E2E & PG15 tests directly on local Windows workstation | Requires active Docker Desktop daemon and local PostgreSQL/Redis | Not executed locally (Docker Desktop stopped on host); fully verified on Ubuntu Linux CI (`46157049085`) | Local Windows Host | **BLOCKED LOCALLY (CI PASS)** |
| **TC-13** | External Staging | Live remote staging deployment, TLS certs, real S3/SMTP, and remote backup drill | Staging host responds over HTTPS with full external integrations | External staging infrastructure not yet provisioned | Remote Staging | **NOT YET EXECUTED** |
