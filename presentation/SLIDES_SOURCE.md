# Sakura AI — College Evaluation Presentation Source (19 Slides)

> Editable Markdown source for [`Sakura_AI_Academic_Presentation.pptx`](Sakura_AI_Academic_Presentation.pptx). Re-generate the compiled PowerPoint deck anytime by running `python presentation/build_presentation.py` from the repository root.

---

## Slide 1 — Title Slide
- **Title:** Sakura AI
- **Subtitle:** A Full-Stack Multi-Agent AI Workspace with Hybrid Semantic RAG, Durable Multi-Worker Orchestration, and Isolated Docker Code Execution
- **Student:** `[Student Name]` (`[Roll Number]`)
- **Guide:** `[Faculty Guide Name, Designation]`
- **Institution & Year:** `[Department of Computer Science & Engineering, Institution Name]` | `[Academic Year]`

## Slide 2 — Project Introduction
- Full-stack multi-tenant AI platform uniting conversational reasoning, document intelligence, media generation, voice transcription, scheduled tasks, and autonomous repository coding.
- Built with **Next.js 14 (TypeScript)**, **FastAPI (Python 3.11+)**, **PostgreSQL 15 + `pgvector`**, **Redis 7**, and an **isolated remote Docker sandbox**.
- Designed for production systems reliability: 32 relational tables, 4 standalone workers, strict tenant isolation, and 4 automated CI pipelines.

## Slide 3 — Problem Statement
- **Single-Vendor Fragility & Privacy Risk:** Hardcoded LLM wrappers fail during outages and risk leaking private prompts to external clouds.
- **Weak Retrieval & Data Mixing:** Vector-only search misses exact identifiers; unscoped vector stores risk cross-user data leakage.
- **Volatile Background Processing:** In-memory async tasks disappear on crashes and corrupt state under concurrent workers.
- **Unsafe Code Execution:** Running AI-generated shell commands directly on the API host exposes credentials and sibling files.

## Slide 4 — Project Objectives
1. Deliver a unified, multi-user AI workspace with streaming chat, memory, library, media, scheduling, and coding.
2. Route prompts across multiple LLM providers with transient failover and fail-closed local privacy (`Ollama`).
3. Implement per-user Hybrid RAG fusing `pgvector(1536)` cosine search with Okapi BM25 via Reciprocal Rank Fusion.
4. Build crash-safe, lease-fenced background workers and asynchronous storage deletion outbox.
5. Isolate untrusted coding execution inside non-root (`1001:1001`), network-disabled Docker containers.
6. Verify correctness continuously via automated unit, PostgreSQL, Docker sandbox, and Playwright E2E CI.

## Slide 5 — Existing System & Limitations
- **Closed Commercial Suites:** High quality, but proprietary, vendor-locked, and non-customizable for local privacy boundaries.
- **Open-Source Chat Wrappers:** Minimal wrappers lacking durable queues, hybrid BM25+vector search, daily quotas, and outbox storage cleanup.
- **Local CLI Coding Agents:** Execute with full developer host privileges—unsafe for hosted multi-user web platforms.

## Slide 6 — Proposed System (Sakura AI)
- **Comparative Advantage Table:** Multi-provider failover + private Ollama mode; Hybrid `pgvector` + BM25 RRF; PostgreSQL authoritative durable queues with lease fencing; Remote Docker `sandbox-executor` (`UID 1001`, `--network none`); `HTTP 202` outbox storage purge; Header-only `PyJWT` auth + daily quotas.

## Slide 7 — Technology Stack
- **Frontend:** Next.js 14, React 18, TypeScript 5, Tailwind CSS, Framer Motion
- **Backend API & Workers:** Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, Pydantic v2, PyJWT, Passlib
- **Data & Search:** PostgreSQL 15, `pgvector` (`vector(1536)`), Okapi BM25 + RRF (SQLite local dev parity)
- **Coordination & Storage:** Redis 7 (AOF + `noeviction`), Boto3 S3-compatible / Local FS
- **AI & Media:** Groq, OpenAI, Anthropic, Local Ollama, OpenAI Embeddings & Whisper, Pollinations, Tavily
- **Isolation & DevOps:** Docker, Docker Compose, Nginx TLS, GitHub Actions CI, Playwright

## Slide 8 — System Architecture
- Visual 10-service layered architecture diagram (Browser -> Nginx -> Next.js + FastAPI -> PostgreSQL 15 + Redis 7 + Object Storage -> 4 Standalone Workers -> Remote `sandbox-executor` -> Ephemeral Non-Root Containers).

## Slide 9 — Database Architecture
- **32 Normalized SQLAlchemy Tables** across 6 domains managed by **11 sequential Alembic migrations** (`8936a43c2fb5` -> `j9f7a263b56c`).
- Native PostgreSQL `vector(1536)` on `document_chunks.embedding` (transparent `JSON` variant on SQLite).
- Lease-fencing columns (`worker_id`, `execution_attempt_id`/`claim_token`, `lease_expires_at`) and idempotency/unique constraints.

## Slide 10 — Major Modules
- 6 visual capability cards spanning all 14 implemented modules: Auth & Account Lifecycle, Conversational AI & Memory, Document Library & Hybrid RAG, Multimodal Image & Audio, Durable Tasks & Cron Scheduler, and Sakura Coding Engine & Projects.

## Slide 11 — AI Routing & Hybrid RAG Workflow
- Custom visual pipeline diagram illustrating: Document Parse (`pdfplumber`, 800-char/150-overlap) -> `text-embedding-3-small` (`1536-d` or honest `NULL` BM25 fallback) -> Strict `user_id` Tenant Filter -> `pgvector` Cosine + Okapi BM25 (`k1=1.5, b=0.75`) -> Reciprocal Rank Fusion -> Intent-Routed LLM Streaming (Fail-Closed Ollama for Private Mode).

## Slide 12 — Sakura Coding Engine & Docker Sandbox
- Custom visual diagram illustrating: Coding API -> `coding_jobs` (Lease-Fenced) -> Standalone `coding-worker` (21-Tool Agent + SSE Replay) -> Authenticated HTTP `sandbox-executor` (Sole `/var/run/docker.sock` Host) -> Ephemeral Container (`--user 1001:1001`, `--network none`, `--cap-drop ALL`, `2 CPU / 512 MB / 64 PIDs`, single-workspace mount, Redis single-use HMAC network capability).

## Slide 13 — Security Architecture
- Four defense-in-depth pillars:
  1. **Auth & Session:** `PyJWT` (`HS256`), `pbkdf2_sha256`, header-only file auth (`?token=` rejected `401`), single-use 60s WS tickets.
  2. **Tenant & Input Guards:** Strict `user_id` scoping (`404`), malformed UUID rejection (`400`), forged internal task blocking (`400`).
  3. **Abuse & Secret Control:** Fail-closed Redis rate limits (`503`), CIDR-validated proxy IPs, atomic daily quotas, startup secret guards.
  4. **Container & Frontend Hardening:** Non-root sandbox (`0` orphaned containers), `images.unoptimized: true` (`/ _next/image` -> `404`).

## Slide 14 — Implementation Screenshots
- 2×2 showcase of actual live screenshots captured from the running local Sakura AI application: Landing Page, Login Screen, Authenticated Chat Workspace, and FastAPI Swagger OpenAPI Docs.

## Slide 15 — Testing & Verified Results
- Actual verified metrics (zero fabricated numbers):
  - **253 / 253 active local backend tests PASSED** (`18` PG/Docker-gated skipped on SQLite, `0` failures).
  - **37 / 37 live full-stack API & UI journeys PASSED** (`0` failures).
  - **4 / 4 GitHub Actions CI jobs PASSED** (Run `46157049085` on `d8de865`): Real PostgreSQL 15 + `pgvector` (0 skips), backup/restore tamper test, real Docker sandbox E2E, unmocked Playwright E2E, **0 orphaned containers**.

## Slide 16 — Known Limitations
- External staging host (TLS, managed PG15/Redis/S3/SMTP) not yet provisioned.
- Frontend runs `next@14.2.35` (`/_next/image` mitigated via `images.unoptimized: true`; Next 16 + React 19 upgrade tracked as follow-up PR).
- Image edits/variations use prompt-context regeneration (`image_conditioned_edit: false` truthfully reported).
- GitHub connector is live; non-GitHub third-party connectors honestly return `HTTP 501`.
- Dense embeddings and Whisper transcription require `OPENAI_API_KEY` (graceful BM25 fallback when unset).

## Slide 17 — Future Enhancements
- Provision controlled private staging & run load/failover drills.
- Upgrade Next.js 14 -> 16 (React 19) and add automated `pip-audit`/`npm audit` CI gates.
- Add local open-source embeddings + `pgvector` HNSW indexes + PostgreSQL `tsvector` lexical scaling.
- Evaluate Firecracker/gVisor microVM runtime for public multi-tenant coding execution.
- Add Prometheus/OpenTelemetry metrics and OAuth document connectors.

## Slide 18 — Conclusion
- Sakura AI delivers a verifiable, production-patterned multi-agent AI platform rather than a fragile chat demo.
- Combines modern AI workflows (Hybrid RAG, multi-provider streaming, autonomous coding) with core computer science fundamentals (ACID migrations, lease fencing, outbox pattern, kernel/container isolation).
- Ready for college project evaluation, technical viva defense, and controlled staging deployment.

## Slide 19 — Questions & Answers
- Thank You & Live Demo Ready (`http://localhost:3000`)
- Repository: `https://github.com/Abhiram-C-Divakaran/Sakura-AI`
- Companion Docs: `docs/academic/PROJECT_REPORT.md`, `docs/architecture/`, `docs/interview/VIVA_QUESTIONS_AND_ANSWERS.md`, `docs/DEMO_PLAYBOOK.md`
