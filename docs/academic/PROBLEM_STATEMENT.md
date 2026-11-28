# Sakura AI — Problem Statement & Project Motivation

> Companion standalone document to Chapter 1 & Chapter 2 of [`PROJECT_REPORT.md`](PROJECT_REPORT.md).

---

## 1. Problem Statement

Developers, researchers, and students increasingly rely on fragmented tools—separate chat apps, standalone document search engines, image generators, task schedulers, and local coding agents—to accomplish daily technical work. Conversely, existing unified open-source AI workspaces frequently exhibit critical architectural weaknesses:

1. **Vendor Lock-In and Silent Privacy Leakage:** Hardcoding a single commercial LLM provider creates operational fragility during upstream outages, while naive fallbacks can silently forward sensitive or private prompts to third-party cloud APIs.
2. **Brittle Retrieval Quality and Multi-Tenant Data Leakage:** Dense-only vector search misses exact technical identifiers (error codes, symbols, function names), while unpartitioned vector stores risk leaking one user's document chunks into another user's prompt context.
3. **Unsafe Execution of AI-Generated Code:** Coding assistants that invoke `subprocess` directly on the application host expose backend environment variables, database credentials, sibling user workspaces, and cloud metadata endpoints to untrusted code.
4. **Volatile In-Memory Background Processing:** Long-running document indexing, image generation, scheduled tasks, and storage cleanup run inside web-request threads or ephemeral memory lose jobs upon server restarts and suffer split-brain race conditions under multi-worker scaling.
5. **Incomplete Security Lifecycle:** Prototype systems routinely expose JWTs in URL query parameters (`?token=`), omit per-user usage quotas, skip authenticated account deletion/export, and fail open when rate-limiting stores go offline.

---

## 2. Core Research & Engineering Objectives

Sakura AI was designed and implemented to satisfy seven measurable engineering objectives:

1. **Unified Multimodal Workspace:** Deliver conversational AI (SSE streaming), persistent memory, document intelligence, voice transcription, raster image generation, project organization, scheduled tasks, and repository-level coding inside one responsive Next.js web application.
2. **Provider-Neutral Routing & Privacy Enforcement:** Support OpenAI, Anthropic, Groq, and local Ollama with transient-only failover and a strict fail-closed privacy mode for local-only prompts.
3. **Hybrid Semantic + Lexical RAG:** Fuse native PostgreSQL `pgvector` (`vector(1536)`) dense cosine similarity with Okapi BM25 lexical ranking via Reciprocal Rank Fusion (RRF), strictly scoped per authenticated user.
4. **Crash-Safe Durable Multi-Worker Execution:** Make PostgreSQL the authoritative state store for all asynchronous jobs, scheduled occurrences, and object-storage deletions, protected by atomic claims and unexpired-lease fencing.
5. **Defense-in-Depth Coding Sandbox:** Isolate AI-generated code execution inside ephemeral, non-root (`1001:1001`), network-disabled Docker containers orchestrated exclusively through an authenticated remote `sandbox-executor` service.
6. **Multi-Tenant Security & Account Governance:** Enforce `PyJWT` (`HS256`) auth, header-only file downloads, single-use WebSocket tickets, Redis-backed fail-closed rate limiting, atomic daily quotas, data export (ZIP), and audited self-service account deletion.
7. **Reproducible Automated Verification:** Validate schema parity, migrations, PostgreSQL concurrency, backup/restore scripts, Docker sandbox isolation, and full-stack browser journeys continuously in GitHub Actions CI.
