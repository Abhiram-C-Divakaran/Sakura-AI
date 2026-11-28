# Sakura AI — Known Limitations & Future Enhancements

> Companion standalone document to Chapter 11 of [`PROJECT_REPORT.md`](PROJECT_REPORT.md). All limitations below reflect verified repository facts rather than speculative assumptions.

---

## 1. Verified Current Limitations

1. **No Live Public Staging / Production Host Provisioned Yet:** While `anime-ai/docker-compose.prod.yml`, `ops/nginx.conf.example`, `ops/scripts/validate_env.py`, and backup/restore scripts are implemented and verified in GitHub Actions CI, an external staging server with live DNS/TLS, managed PostgreSQL 15, Redis 7, S3 bucket credentials, and SMTP delivery has not yet been provisioned.
2. **Next.js 14 to Next.js 16 Dependency Upgrade Pending:** The frontend currently runs on `next@14.2.35` (React 18). Live `npm audit --omit=dev` flagged upstream advisories in `next`, `postcss`, and `source-map-js`. Phase 1 mitigated the unused `/_next/image` attack surface immediately via `images: { unoptimized: true }` (verified HTTP `404`), while the breaking Next.js 16 + React 19 upgrade is deferred to a dedicated post-merge PR.
3. **Prompt-Context Image Editing vs. Pixel-Level Conditioning:** Image variations and edits (`media/image_engine.py`) operate via prompt-context regeneration and lineage tracking rather than native pixel-mask inpainting or neural super-resolution; `/api/v1/capabilities` truthfully reports `image_conditioned_edit: false` and `true_upscale: false`.
4. **Partial Third-Party Connector Coverage:** GitHub repository integration (`api/integrations.py`) is fully implemented with live API verification and Fernet-encrypted token storage. Google Drive, Notion, Slack, Jira, and external PostgreSQL connectors intentionally return `HTTP 501 Not Implemented` rather than presenting deceptive mock connectors.
5. **Embedding & Audio Provider Dependency:** Dense semantic embeddings (`text-embedding-3-small`, 1536-d) and Whisper audio transcription (`api/audio.py`) currently require `OPENAI_API_KEY`. When omitted, RAG gracefully and truthfully falls back to Okapi BM25 lexical retrieval (`embedding = NULL`, zero fake random vectors).
6. **Non-Blocking Frontend ESLint Warnings & Draft Legal Pages:** `next lint` passes with 0 errors but retains 10 pre-existing React hook dependency / `<img>` / `alt` warnings. Public `/privacy` and `/terms` pages are pre-launch drafts requiring legal review prior to commercial deployment.
7. **Local Windows Dev Environment Parity:** On developer workstations without running Docker Desktop, local `psql`, or local `redis-server`, Sakura AI runs in SQLite development mode (`DEGRADED` readiness) with local restricted subprocess fallback; full container isolation and `pgvector` concurrency require Linux/Docker (verified in CI).

---

## 2. Realistic Future Enhancements

1. **Controlled Private Staging Rollout & Load Testing:** Provision a hardened staging environment separating the `sandbox-executor` host (sole Docker socket boundary) from application servers, execute live backup/restore drills, and run k6/Locust load tests across SSE streaming and worker queues.
2. **Next.js 16 + React 19 Migration & Dependency Auditing in CI:** Upgrade the frontend framework to clear upstream `npm audit` findings, resolve the remaining 10 ESLint warnings, and add automated `pip-audit` and `npm audit` gates to `.github/workflows/ci.yml`.
3. **Pluggable Local & Multi-Provider Embeddings:** Support local sentence-transformer / Ollama embedding adapters alongside OpenAI embeddings (with explicit dimension/model tracking per chunk) to enable 100% air-gapped dense Hybrid RAG.
4. **HNSW / IVFFlat Vector Indexing & Cross-Encoder Reranking:** Add PostgreSQL `pgvector` HNSW indexes and an optional cross-encoder reranker stage on top of RRF candidates to maintain sub-50 ms retrieval latency at millions of chunks.
5. **MicroVM Sandbox Runtime Option:** Extend `BaseSandboxRuntime` (`coding/sandbox.py`) to support Firecracker or gVisor (`runsc`) runtimes alongside hardened Docker containers for multi-tenant public SaaS threat models.
6. **Observability & Telemetry Stack:** Export Prometheus metrics (worker queue depth, lease expiry rate, LLM token latency, quota hits) and OpenTelemetry distributed traces correlated via the existing `X-Request-ID` middleware.
7. **Pixel-Conditioned Image Pipeline & OAuth Connectors:** Integrate true mask-based image editing/inpainting models and implement OAuth 2.0 flows for Google Drive, Notion, and Slack document synchronization.
