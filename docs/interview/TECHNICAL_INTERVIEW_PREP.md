# Sakura AI — Technical Interview Preparation Guide

> Focused guide for software engineering, backend, and full-stack AI interviews. Pair with [`VIVA_QUESTIONS_AND_ANSWERS.md`](VIVA_QUESTIONS_AND_ANSWERS.md) (50 viva Q&As + 8 senior deep-dives) and [`ARCHITECTURE_EXPLANATIONS.md`](ARCHITECTURE_EXPLANATIONS.md).

---

## 1. Resume Bullet Points (Grounded in Verified Evidence)

- **Architected a full-stack multi-tenant AI workspace** (FastAPI, Next.js 14/TypeScript, PostgreSQL 15 + `pgvector`, Redis 7, Docker) spanning 32 normalized ORM tables, 11 Alembic migrations, multi-provider SSE streaming, and real-time WebSockets.
- **Engineered Hybrid Retrieval-Augmented Generation (RAG)** combining native PostgreSQL `pgvector(1536)` cosine distance with Okapi BM25 (`k1=1.5`, `b=0.75`) via Reciprocal Rank Fusion (RRF), generation-fenced indexing, and strict per-user tenant scoping.
- **Built crash-safe durable multi-worker orchestration** (`worker`, `image-worker`, `coding-worker`, timezone-aware `scheduler`) using PostgreSQL `FOR UPDATE SKIP LOCKED`, unexpired-lease fencing (`execution_attempt_id` / `claim_token`), and a killable-subprocess `StorageDeletionOutbox`.
- **Designed defense-in-depth remote Docker sandbox execution** isolating `/var/run/docker.sock` behind an authenticated HTTP executor running ephemeral non-root (`1001:1001`) containers with `--network none`, `--cap-drop ALL`, CPU/RAM/PID limits, and Redis-enforced single-use HMAC capability tokens.
- **Established multi-layer automated CI verification** (253 passing local backend tests + 4 required GitHub Actions workflows testing real PostgreSQL 15 `pgvector`, `pg_dump`/`pg_restore` tamper detection, real Docker sandbox isolation, and unmocked Playwright browser E2E with 0 orphaned containers).

---

## 2. Key Architectural Trade-Offs to Highlight

| Decision | Trade-Off Considered | Why Sakura AI Chose This Design |
| --- | --- | --- |
| **PostgreSQL `pgvector` over Pinecone/Qdrant** | Slightly lower specialized vector scale at 100M+ rows without sharding | Eliminates dual-write consistency bugs; keeps tenant FK cascades, outbox state, and vectors ACID-atomic |
| **PostgreSQL Queue + Redis Wakeups over Celery/RabbitMQ** | Slightly more custom claim/lease SQL to maintain | Single transactional store for jobs + domain data (outbox pattern), zero lost tasks on Redis restart, explicit lease fencing |
| **Separate `sandbox-executor` HTTP service** | Adds one internal network hop (~2–5 ms) | Removes `/var/run/docker.sock` completely from the web API and coding worker blast radius |
| **`images.unoptimized: true` on Next 14 vs. immediate Next 16 jump** | Keeps `next@14.2.35` until dedicated React 19 PR | Immediately neutralizes `/_next/image` advisories (`HTTP 404`) without risking destabilizing PR #1 |
| **Honest BM25 fallback & `HTTP 501` stubs** | Fewer "demo-only" fake green lights | Guarantees operational truthfulness in `/readiness` and `/api/v1/capabilities` |

---

## 3. High-Impact Engineering Stories (STAR Format)

### Story A: Preventing Split-Brain Corruption Under Worker Lease Expiry
- **Situation:** Multiple durable workers (`worker`, `image-worker`, `coding-worker`) process long-running jobs; a paused worker waking up after lease expiry could overwrite a reclaimed job's state.
- **Task:** Guarantee mathematically that a stale worker can never commit a terminal status or mutate an outbox row after losing its lease.
- **Action:** Added `execution_attempt_id`/`claim_token` + `lease_expires_at` fencing across all worker tables and enforced conditional terminal `UPDATE` queries (`WHERE id=? AND attempt_id=? AND lease_expires_at > NOW()`), plus regression tests simulating expired leases *before* recovery runs.
- **Result:** Verified zero split-brain overwrites under concurrent PostgreSQL 15 worker tests in CI (`test_postgres_pgvector_and_concurrency.py`).

### Story B: Eliminating URL Token Leakage & Unmaintained JWT Libraries
- **Situation:** Browser file downloads (`<img>`, `<a href>`) and WebSockets commonly tempt developers to pass JWTs in `?token=`, leaking secrets into proxy logs, while `python-jose` remained unmaintained.
- **Task:** Remove JWTs from all URLs and modernize JWT signing without breaking frontend media previews.
- **Action:** Migrated `AuthManager` to `PyJWT` (`HS256`), enforced header-only `Authorization: Bearer` on file endpoints (rejecting `?token=` with `401`), implemented Blob-based `AuthenticatedImage` and `FilePreviewModal`, and added single-use 60s database-backed WebSocket tickets.
- **Result:** Verified in 22 fail-closed security regression tests and 37/37 live full-stack checks.

### Story C: Isolating Untrusted AI-Generated Code Execution
- **Situation:** An autonomous coding agent needs to run tests and shell commands inside user repositories without risking host compromise or cross-tenant reads.
- **Task:** Build a repeatable, CI-verifiable sandbox isolation boundary.
- **Action:** Built `coding/sandbox_service.py` as the sole Docker socket host, enforced non-root `1001:1001`, `--network none`, `--cap-drop ALL`, CPU/memory/PID limits, allowlisted env vars, single-workspace bind mounts, single-use Redis-verified HMAC capabilities for networked commands, and kill-before-remove timeout cleanup.
- **Result:** Proven in GitHub Actions `Docker Sandbox E2E Integration` and `Full-Stack Integration Tests` with `0` orphaned containers.

---

## 4. Being Candid About What Is Not Yet Done

Strong engineering candidates earn trust by stating real boundaries clearly:
- **No external staging host provisioned yet** (TLS, managed PG15/Redis/S3/SMTP, and remote load tests are next).
- **Next.js 14 -> 16 + React 19 upgrade** is planned as a focused post-merge PR.
- **Non-GitHub connectors** intentionally return `501`, and **image editing** is prompt-context regeneration (`image_conditioned_edit: false`).
- **BM25 scoring** currently runs per-user in Python; at enterprise scale, migrating lexical scoring to PostgreSQL `tsvector` + GIN alongside `pgvector` HNSW indexes is the clear next step.
