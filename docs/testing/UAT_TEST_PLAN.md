# Sakura AI — User Acceptance Testing (UAT) Plan

**Repository:** `https://github.com/Abhiram-C-Divakaran/Sakura-AI`  
**Branch:** `hardening/outbox-pgvector-staging-readiness`  
**Target Release Candidate:** PR `#1` (`03e213d` + Phase 3 UAT evidence)

---

## 1. UAT Scope & Classification Rules

This plan defines structured end-to-end User Acceptance Tests across all eight functional and security domains of Sakura AI (Sections A–H), verifying real user workflows rather than merely confirming endpoint existence.

### Result Classifications
| Status | Definition |
| --- | --- |
| **PASS** | Executed end-to-end against real runtime or CI infrastructure and matched expected outcome. |
| **FAIL** | Executed and diverged from expected outcome (confirmed defect or broken flow). |
| **BLOCKED** | Could not execute in the target environment due to an absent external dependency or unprovisioned service (e.g., missing `SMTP_HOST`, unset `OPENAI_API_KEY`, stopped local Docker daemon). Never misclassified as `PASS` or `FAIL`. |
| **NOT TESTED** | No execution was attempted in this phase. |
| **NOT IMPLEMENTED** | Capability intentionally does not exist in the current implementation (e.g., non-GitHub third-party connectors returning `HTTP 501`, pixel-mask image inpainting). |

---

## 2. Test Environments Covered

| Environment ID | Configuration | What It Proves |
| --- | --- | --- |
| **ENV-LOCAL-LIVE** | Windows host running FastAPI (`:8000`, SQLite migrated to `j9f7a263b56c`, live `GROQ_API_KEY`), Next.js 14 (`:3000`), and Playwright Chromium (desktop `1440×900` + mobile `390×844`). Redis, Docker Desktop, SMTP, and OpenAI keys not active locally. | Live full-stack browser UX, real Groq SSE streaming, PyJWT auth, live WebSocket tickets, library/RAG parsing & BM25 retrieval, coding workspace tools, scheduled CRUD, and multi-tenant API isolation. |
| **ENV-LOCAL-UNIT** | Isolated temporary SQLite DB (`unittest discover`), `tsc --noEmit`, `next lint`, `next build`. | 253 active backend unit/security regression tests + clean frontend static compilation and bundle build. |
| **ENV-CI-LINUX** | GitHub Actions Ubuntu Linux (Run `46167864598` on `03e213d`): Real PostgreSQL 15 (`pgvector/pgvector:pg15`), Redis 7, remote Docker `sandbox-executor`, 3 separate durable workers, FastAPI API, Next.js frontend, official `postgres:15` backup/restore, and unmocked Playwright Chromium. | Real PostgreSQL `pgvector(1536)` retrieval, `FOR UPDATE SKIP LOCKED` concurrency, outbox lease fencing, backup/restore tamper checks, real non-root Docker sandbox isolation (`0` orphans), and unmocked production-topology browser E2E. |
| **ENV-STAGING** | External cloud/VM staging host with TLS, managed PG15/Redis/S3/SMTP. | **Not yet provisioned** — explicitly marked `BLOCKED` where required. |

---

## 3. UAT Workflow Domains (A–H)

| Domain | Test IDs | Key Workflows Validated |
| --- | --- | --- |
| **A. Auth & Account Lifecycle** | `UAT-A01` – `UAT-A12` | Password strength validation, registration, invalid login rejection, PyJWT login, unauthenticated rejection, tampered JWT rejection, live WebSocket single-use ticket + replay rejection, quotas, async ZIP export, password reset API (SMTP check), browser reload session persistence, isolated test-account deletion & post-delete login rejection. |
| **B. AI Conversation System** | `UAT-B01` – `UAT-B09` | Conversation creation, live SSE token streaming (Groq), persisted history across refresh, full-text search, pin/unpin/archive, share link create/public read/revoke, message feedback, cross-user conversation isolation (`404`), and fail-closed `local_private` routing (`LLMRouter`). |
| **C. Document Intelligence & RAG** | `UAT-C01` – `UAT-C10` | Real PDF, Markdown, and TXT uploads containing unique synthetic canary facts (`QOTG-9472`, port `7741`, `Sapphire-7`), preview (`/content`), Bearer download, `?token=` rejection (`401`), cross-user isolation (`404`), indexing trigger, chunk parsing & Okapi BM25 canary retrieval, PostgreSQL `pgvector(1536)` + hybrid RRF (CI), and async `HTTP 202` outbox deletion. |
| **D. Image & Media Functionality** | `UAT-D01` – `UAT-D07` | Durable image job creation, `idempotency_key` replay deduplication, status polling, variation payload-mismatch `HTTP 409` (CI/unit), invalid audio extension rejection (`400`), Whisper transcription (honest `BLOCKED` locally when `OPENAI_API_KEY` unset), and honest `NOT IMPLEMENTED` classification for pixel-mask inpainting. |
| **E. Sakura Coding Engine & Sandbox** | `UAT-E01` – `UAT-E10` | Workspace creation, cross-user isolation (`404`), file write/read/git diff tools, path traversal blocking, durable coding job submission, sequential events replay (`after_sequence`), cancellation, and full remote Docker sandbox isolation (non-root `UID 1001`, `--network none`, resource limits, HMAC capability, `0` orphans in CI). |
| **F. Background Workers & Scheduling** | `UAT-F01` – `UAT-F07` | Allowed background task creation, forged internal task rejection (`400`), scheduled task CRUD with IANA timezone (`Asia/Kolkata`) + runs history, PostgreSQL `FOR UPDATE SKIP LOCKED` claims, lease expiry recovery, stale-worker conditional write fencing, and unique occurrence deduplication (CI/unit). |
| **G. File & Library Management** | `UAT-G01` – `UAT-G04` | File rename (`PATCH`), Library UI view & empty states, ownership enforcement, and storage persistence across restarts. |
| **H. Security, UX & Responsive Audit** | `UAT-H01` – `UAT-H06`, `UX-01` – `UX-10` | Malformed UUID (`400`), `/_next/image` disabled (`404`), `/readiness` zero secret leakage, Redis fail-closed rate limits (`503` in prod), unauthenticated `/chat -> /login` redirect, desktop & mobile (`390×844`) responsive overflow checks, sidebar navigation, and zero uncaught pageerrors. |

---

## 4. Safety & Non-Destructive Rules
1. Every live UAT run creates unique ephemeral test users (`uat_*_<hex>`) and cleans them up via `DELETE /api/v1/auth/me` in a `finally` block.
2. No pre-existing user data or databases are ever deleted or overwritten.
3. No real API keys, tokens, or `.env` values are printed into logs, test reports, or screenshots.
