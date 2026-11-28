# Sakura AI — Architecture Explanations for Viva & Whiteboard Interviews

Concise oral walkthroughs designed to help you explain Sakura AI clearly to college faculty (who may not specialize in AI systems) and senior software engineering interviewers.

---

## 1. The 60-Second Elevator Pitch (For Faculty & Recruiters)

> "Sakura AI is a full-stack multi-user AI platform built with Next.js, FastAPI, PostgreSQL 15 with `pgvector`, Redis 7, and Docker. Instead of wrapping a single chat API, it brings together streaming multi-provider chat, Hybrid RAG document search, image generation, voice transcription, scheduled jobs, and an autonomous coding engine inside one workspace. What makes it engineering-grade is how it handles reliability and security: PostgreSQL is the single source of truth across 32 tables and 4 independent lease-fenced background workers, private prompts fail closed to local Ollama, and AI-generated code runs exclusively inside non-root, network-disabled Docker containers via a separate sandbox executor service—all verified by 253 local tests and 4 automated GitHub Actions CI pipelines."

---

## 2. Three-Minute Whiteboard Walkthrough

When asked *"Draw and explain your architecture on the board"*, sketch four vertical columns from left to right:

1. **Client & Edge:** Next.js 14 (TypeScript) behind Nginx TLS. Point out two intentional details: header-only Bearer auth (zero JWTs in URLs, Blob previews) and single-use 60-second tickets for WebSockets.
2. **Stateless API Tier:** FastAPI (`:8000`) with `X-Request-ID` middleware, Redis sliding-window rate limits (CIDR-validated proxy headers), atomic daily quotas, and `LLMRouter` (Groq / OpenAI / Anthropic / fail-closed local Ollama).
3. **Stateful Data & Durable Workers:** PostgreSQL 15 + `pgvector(1536)` (32 tables, 11 Alembic migrations) paired with Redis 7 (AOF + `noeviction`). Four standalone workers (`worker`, `image-worker`, `coding-worker`, `scheduler`) claim jobs via `FOR UPDATE SKIP LOCKED` and guard terminal commits with `execution_attempt_id` + `lease_expires_at > NOW()`.
4. **Isolated Sandbox Tier:** Remote `sandbox-executor` (`:9000`) is the **only** component with `/var/run/docker.sock`. It spawns ephemeral `--user 1001:1001`, `--network none`, `--cap-drop ALL`, `2 CPU / 512 MB / 64 PID` containers mounted to a single workspace, requiring single-use HMAC capability tokens for any networked command.

---

## 3. Explaining Complex Concepts Simply to Non-AI Faculty

| Technical Concept | Plain-Language Explanation for Viva Panel |
| --- | --- |
| **Hybrid RAG (`pgvector` + BM25 + RRF)** | "Vector search finds paragraphs with similar *meaning* even if words differ; BM25 finds *exact* terms like roll numbers, error codes, or function names. Reciprocal Rank Fusion merges both ranked lists so answers are both smart and exact—and strictly limited to the logged-in user's files." |
| **Lease Fencing** | "Think of a library checkout timestamp. If Worker 1 freezes past its deadline and Worker 2 takes over the task, Worker 1's expired receipt is rejected by the database when it wakes up, so it can never overwrite Worker 2's newer result." |
| **Storage Deletion Outbox** | "Deleting a file from cloud storage can take seconds or fail if the network blips. Instead of freezing the user's click or leaving orphaned files behind, we record a deletion receipt in PostgreSQL, return `202 Accepted` immediately, and let a background worker safely finish the deletion with retries." |
| **Docker Sandbox Isolation** | "Running AI-written code directly on the web server is like letting a stranger type commands into your admin terminal. Instead, we hand the code to a locked, non-admin mini-container with no internet access, limited memory, and visibility into only one project folder, then destroy the container when done." |
| **Single-Use HMAC Capability** | "If a coding task legitimately needs internet access (like installing a package), the user approves that exact command. The backend signs a one-time digital permission slip valid only for that workspace and command; Redis shreds the slip the instant it's used so it can never be replayed." |
