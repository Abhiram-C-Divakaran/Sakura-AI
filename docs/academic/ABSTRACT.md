# Sakura AI — Project Abstract

**Project Title:** Sakura AI: A Full-Stack Multi-Agent AI Workspace with Hybrid Semantic RAG, Durable Multi-Worker Orchestration, and Isolated Docker Code Execution  
**Student Name:** `[Student Name]`  
**Registration / Roll Number:** `[Roll Number]`  
**Department & Institution:** `[Department of Computer Science & Engineering, Institution Name]`  
**Project Guide:** `[Faculty Guide Name, Designation]`  
**Academic Year:** `[Academic Year, e.g., 2025–2026]`

---

## Abstract

Modern Artificial Intelligence (AI) assistants have rapidly evolved from single-turn chat interfaces into multi-capability software workspaces encompassing conversational reasoning, enterprise document question-answering, multimodal media generation, and autonomous code editing. However, many open-source and academic implementations remain fragile wrappers around external Large Language Model (LLM) APIs: they rely on unisolated in-process background tasks, lack persistent recovery under worker crashes, mix user data across shared vector indices, embed authentication secrets in query strings, or execute AI-generated shell commands directly on the host operating system.

**Sakura AI** addresses these systemic engineering gaps by designing and implementing a full-stack, multi-tenant AI platform engineered for correctness, security, and operational durability. The platform pairs a **Next.js 14 (React 18 / TypeScript)** frontend with a modular **FastAPI (Python 3.11+)** backend, backed by **PostgreSQL 15 with `pgvector` (`vector(1536)`)** across **32 normalized relational tables** managed through **11 sequential Alembic migrations**, and **Redis 7** configured with Append-Only File (AOF) persistence and `noeviction`.

Key technical contributions implemented and verified in Sakura AI include:
1. **Provider-Neutral Conversational Routing with Fail-Closed Privacy:** Dynamic intent-based routing and transient-only failover across Groq, OpenAI, Anthropic, and local Ollama, strictly enforcing a fail-closed privacy boundary (`PrivateModelUnavailableError`) so private prompts never leak to cloud APIs.
2. **Per-User Hybrid Retrieval-Augmented Generation (RAG):** Asynchronous document parsing (`PDF`, `Markdown`, `TXT`, source code), 800-character overlapping chunking, native `pgvector(1536)` cosine distance search fused with Okapi BM25 (`k1=1.5`, `b=0.75`) via Reciprocal Rank Fusion (RRF), generation-fenced re-indexing, and honest BM25 fallback when embedding keys are unconfigured.
3. **Database-Authoritative Durable Multi-Worker Orchestration:** Four dedicated standalone processes (`worker`, `image-worker`, `coding-worker`, and timezone-aware `scheduler`) coordinated via PostgreSQL `FOR UPDATE SKIP LOCKED`, conditional compare-and-swap (CAS) lease fencing (`execution_attempt_id`, `claim_token`, `lease_expires_at`), and killable subprocess storage deletion outbox (`StorageDeletionOutbox`).
4. **Sakura Coding Engine with Defense-in-Depth Docker Sandbox Isolation:** An iterative repository-level coding agent executing untrusted shell/test commands via a dedicated remote HTTP `sandbox-executor` service—the sole service mounting `/var/run/docker.sock`—which launches ephemeral non-root (`UID 1001:1001`) containers with `--network none` by default, `--cap-drop ALL`, CPU/memory/PID caps, single-workspace mounts, and single-use HMAC-SHA256 capability tokens for explicitly authorized network operations.
5. **Security & Verification Rigor:** `PyJWT` (`HS256`) authentication, header-only file access, single-use WebSocket tickets, atomic UTC-day per-user quotas (`user_usage_quotas`), fail-closed Redis rate limiting, and continuous verification through **253 passing local backend tests** plus **4 required GitHub Actions CI pipelines** (real PostgreSQL 15 + `pgvector`, Redis 7, remote Docker sandbox E2E, and unmocked Playwright full-stack E2E with zero orphaned containers).

**Keywords:** Multi-Agent AI Workspace, Hybrid RAG, `pgvector`, Okapi BM25, Reciprocal Rank Fusion, FastAPI, Next.js, Durable Job Queues, Lease Fencing, Docker Sandbox Isolation, Multi-Tenant Security.
