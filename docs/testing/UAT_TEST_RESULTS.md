# Sakura AI — User Acceptance Testing (UAT) Results

**Date Executed:** 2026-11-28  
**Repository & Branch:** `Abhiram-C-Divakaran/Sakura-AI` — `hardening/outbox-pgvector-staging-readiness`  
**Verified Commit & CI:** `03e213db5532d9c59cae6548af80f512555a97fc` — GitHub Actions Run [`46167864598`](https://github.com/Abhiram-C-Divakaran/Sakura-AI/actions/runs/46167864598) (**4/4 PASSED**)  
**Local Live Stack:** FastAPI (`http://127.0.0.1:8000`, SQLite migrated to `j9f7a263b56c`, live `GROQ_API_KEY`) + Next.js 14 (`http://127.0.0.1:3000`) + Playwright Chromium (`1440×900` desktop & `390×844` mobile)

---

## 1. Executive Summary & Classification Counts

| Execution Group | Executed | PASS | FAIL | BLOCKED | NOT IMPLEMENTED | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **Live Local Backend & WebSocket UAT (A–H)** | 51 | 49 | 0 | 2 | 0 | `UAT-A10` (SMTP unconfigured -> honest `503` fail-closed), `UAT-D05` (Whisper `OPENAI_API_KEY` unset -> honest `503`); all 49 runnable live journeys passed |
| **Live Playwright Chromium UX & Mobile Audit** | 19 | 18 | 0* | 0 | 0 | *1 dev-mode Next.js `Abort fetching component` router warning during rapid script navigation (`UX-10`), `0` uncaught pageerrors, `0` mobile overflow |
| **Local Demo Pre-Flight Health Script** | 9 | 9 | 0 | 0 | 0 | `python docs/demo_assets/preflight_check.py` -> `READY FOR DEMO` |
| **Local Automated Unit & Frontend Suites** | 256 | 256 | 0 | 18 | 0 | 253 backend unit tests + `tsc`, `next lint`, `next build`; 18 PG15/Docker tests gated locally -> all 18 pass in CI |
| **GitHub Actions CI (Run `46167864598`)** | 4 jobs | 4 | 0 | 0 | 0 | Real PG15 `pgvector` (0 skips), backup/restore, real Docker Sandbox E2E (`0` orphans), unmocked Playwright E2E |
| **External Staging & Intentionally Unimplemented Scope** | 5 | 0 | 0 | 3 | 2 | Staging host/TLS/S3/SMTP (`BLOCKED`); non-GitHub connectors (`501`) & pixel-mask image inpainting (`NOT IMPLEMENTED`) |

---

## 2. Detailed UAT Results Matrix (Sections A–H)

### A. Authentication & Account Management
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-A01** | Password strength validation | Backend running | `POST /api/v1/auth/register` with password `"123"` | Rejected with `HTTP 400` | `HTTP 400` rejected weak password | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A02** | Isolated user registration (A & B) | Unique usernames | Register `uat2_a_*` and `uat2_b_*` | Both return `HTTP 200` | User A `200`, User B `200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A03** | Invalid credentials rejection | Registered user A | `POST /api/v1/auth/token` with wrong password | Rejected `HTTP 400`/`401` | `HTTP 400` invalid credentials | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A04** | Login (`PyJWT` `HS256`) | Registered users A & B | Obtain Bearer JWT via `/api/v1/auth/token` | `HTTP 200` + valid `access_token` | `HTTP 200`, valid PyJWT issued for A & B | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A05** | Unauthorized API rejection | None | `GET /api/v1/conversations` without header | `HTTP 401` | `HTTP 401 Unauthorized` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A06** | Tampered JWT rejection | Valid JWT | Mutate last 4 chars of JWT and call API | `HTTP 401` | `HTTP 401` rejected tampered signature | `ENV-LOCAL-LIVE` | Live UAT v2 + unit | **PASS** |
| **UAT-A07** | Live WebSocket ticket & replay block | Authenticated User A | `POST /auth/ws-ticket` -> connect `ws://.../api/v1/ws?ticket=...` -> attempt second connect with same ticket | First connect succeeds; replay rejected | `first_connect=True`, `replay_rejected=True` | `ENV-LOCAL-LIVE` | Live `websockets` test | **PASS** |
| **UAT-A08** | Account daily usage quotas | Authenticated User A | `GET /api/v1/auth/me/quotas` | `HTTP 200` with UTC-day quota counters | `HTTP 200` (`chat`, `image_generation`, `coding_task`, `file_upload`, `scheduled_job`) | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A09** | Async user data export | Authenticated User A | `POST /api/v1/auth/me/export` | `HTTP 202` export job queued | `HTTP 202` with `export_id` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A10** | SMTP password reset delivery | `SMTP_HOST` unset locally | `POST /api/v1/auth/password-reset/request` with `{"identifier": ...}` | Clean fail-closed `503` without SMTP; real email delivery requires SMTP | `HTTP 503` (`"Password reset is disabled ... SMTP delivery or canonical HTTPS PUBLIC_APP_URL is not configured"`) | `ENV-LOCAL-LIVE` | Live UAT v2 (token unit test PASS) | **BLOCKED (No SMTP)** |
| **UAT-A11** | Self-service account deletion & cleanup | Ephemeral users A & B | `DELETE /api/v1/auth/me` with `password` + `confirm="DELETE"`, then attempt login | `HTTP 200` delete; subsequent login fails `400` | Both A & B: `del=200`, `relogin=400` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-A12** | Browser login & reload session persistence | Live FE + BE | Sign in via `/login` UI -> navigate `/chat` -> `page.reload()` | Stays authenticated on `/chat` | `UX-03` & `UX-04` stayed on `/chat` | `ENV-LOCAL-LIVE` | Playwright Chromium | **PASS** |

### B. AI Conversation System
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-B01** | Create conversation | Authenticated User A | `POST /api/v1/conversations` | `HTTP 200` + UUID `id` | `HTTP 200`, UUID returned | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B02** | Live SSE token streaming (Groq) | `GROQ_API_KEY` configured | `POST /api/v1/chat/stream` with exact prompt `"SAKURA_UAT_7741"` | Incremental `data: {"token": ..., "provider": "groq"}` stream | `HTTP 200`, `425` bytes streamed live from `groq` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B03** | Conversation history persistence | Completed stream turn | `GET /api/v1/conversations/{id}/messages` | `>= 2` persisted messages (`user` + `assistant`) | `HTTP 200`, `msgs=2` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B04** | Conversation full-text search | Persisted message | `GET /api/v1/conversations/search?q=SAKURA_UAT_7741` | `HTTP 200` containing conversation UUID | `HTTP 200`, exact conversation matched | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B05** | Pin, unpin & archive | Owned conversation | `POST /pin`, `/unpin`, `/archive` | All return `HTTP 200` | `pin=200`, `unpin=200`, `archive=200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B06** | Share link create, read & revoke | Owned conversation | `POST /share` -> unauth `GET /share/{tok}` -> `DELETE /share/{tok}` -> `GET /share/{tok}` | Public `200`, delete `200`, post-revoke `404` | `get=200`, `del=200`, `after=404` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B07** | Message feedback persistence | Persisted assistant msg | `POST /api/v1/messages/{id}/feedback` | `HTTP 200` | `HTTP 200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B08** | Cross-user conversation isolation | Users A & B | User B requests User A's conversation messages | `HTTP 404` | `HTTP 404` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-B09** | Fail-closed private (`Ollama`) routing | `OLLAMA_BASE_URL` unset, Groq active | Evaluate `LLMRouter().get_ordered_providers('local_private')` | Empty list `[]` (refuses cloud fallback) | Returned `[]` despite active Groq adapter | `ENV-LOCAL-UNIT` | Live Python check + unit | **PASS** |

### C & G. Document Intelligence, Hybrid RAG & Library
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-C01** | Upload PDF, Markdown & TXT canary docs | Authenticated User A | Multipart upload of real PDF 1.4, MD, TXT containing `QOTG-9472` / port `7741` | All 3 return `HTTP 200` + document IDs | PDF `200`, MD `200`, TXT `200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C02** | Document preview (`/content`) | Uploaded MD doc | `GET /api/v1/library/files/{id}/content` | `HTTP 200` containing `7741` | `HTTP 200` with exact canary text | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C03** | Authenticated Bearer file download | Uploaded MD doc | `GET /api/v1/library/files/{id}/download` with Bearer header | `HTTP 200` matching bytes | `HTTP 200` containing `7741` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C04** | Query-string `?token=` rejection | Valid JWT | `GET /api/v1/library/files/{id}/download?token=...` | `HTTP 401` | `HTTP 401` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C05** | Cross-user file download isolation | Users A & B | User B downloads User A's file | `HTTP 404` | `HTTP 404` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C06** | Knowledge-base indexing trigger | Uploaded MD doc | `POST /api/v1/library/files/{id}/index` | `HTTP 200`/`202` indexing queued | `HTTP 200` (`indexing_started`) | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-C07** | Async outbox delete (`HTTP 202`) | Uploaded MD doc | `DELETE /api/v1/library/files/{id}` | `HTTP 202`, `deletion_status="DELETING"` | `HTTP 202`, `status=DELETING` | `ENV-LOCAL-LIVE` | Live UAT v2 + CI PG15 outbox | **PASS** |
| **UAT-C08** | Document parsing & Okapi BM25 canary retrieval | `sample_knowledge_base.md` | Parse + chunk (`DocumentParser`) + score (`BM25Scorer`) for `"Quantum Orchid port 7741 Sapphire-7 cooling"` | Top chunk contains `7741` & `Sapphire-7` | `3` chunks, top BM25 score `3.609`, `HAS_7741=True`, `HAS_SAPPHIRE=True` | `ENV-LOCAL-UNIT` | Live verification | **PASS** |
| **UAT-C09** | Native PostgreSQL `pgvector(1536)` + Hybrid RRF | PG15 + `pgvector` container | Run `test_postgres_pgvector_and_concurrency.py` | 1536-d cosine retrieval + BM25 + RRF pass with `0` skips | Passed with `0` skips in CI Run `46167864598` | `ENV-CI-LINUX` | CI Job `141049333804` | **PASS (CI)** |
| **UAT-G01** | Rename library file (`PATCH`) | Uploaded MD doc | `PATCH /api/v1/library/files/{id}` with `{"name": "horizon_runbook_renamed.md"}` | `HTTP 200` with updated name | `HTTP 200`, name updated | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-G02** | Persistence across full backend restart | Running uvicorn | Create conversation + upload `PERSIST_CANARY_8821` -> kill & restart uvicorn -> re-login & fetch both | Both conversation & file bytes survive restart | `conv_ok=True`, `file_ok=True`, `cleanup=200` | `ENV-LOCAL-LIVE` | Live restart probe | **PASS** |

### D. Image & Audio Media
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-D01** | Durable image job creation | Authenticated User A | `POST /api/v1/images/jobs` with `idempotency_key` | `HTTP 202` + `job_id` | `HTTP 202`, `job_id` returned | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-D02** | Idempotency replay deduplication | Same `idempotency_key` | Repeat identical `POST /api/v1/images/jobs` | Exact same `job_id` returned | `orig == replay` (`1e1ca94d-...`) | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-D03** | Image job status polling | Created job | `GET /api/v1/images/jobs/{id}` | `HTTP 200` job metadata | `HTTP 200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-D04** | Invalid audio extension blocked | Authenticated User A | Upload `bad.exe` to `/api/v1/audio/transcribe` | `HTTP 400` rejected | `HTTP 400` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-D05** | Live Whisper transcription | `OPENAI_API_KEY` unset locally | Upload valid `.wav` to `/api/v1/audio/transcribe` | Requires `OPENAI_API_KEY`; clean `503` when unset | `HTTP 503` (`"audio processing models are not configured"`) | `ENV-LOCAL-LIVE` | Live UAT v2 | **BLOCKED (No OpenAI Key)** |
| **UAT-D06** | Image variation fingerprint conflict (`409`) | PG15 + variation batch | Reuse `idempotency_key` with modified payload | `HTTP 409 Conflict` | Verified in CI PG15 `46167864598` | `ENV-CI-LINUX` | CI Job `141049333804` | **PASS (CI)** |
| **UAT-D07** | Pixel-mask inpainting / true super-resolution | N/A | Inspect `/api/v1/capabilities` | Truthfully reports unsupported | `image_conditioned_edit: false`, `true_upscale: false` | `ENV-LOCAL-LIVE` | `/api/v1/capabilities` | **NOT IMPLEMENTED** |

### E & F. Sakura Coding Engine, Docker Sandbox, Workers & Scheduler
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-E01** | Create isolated coding workspace | Authenticated User A | `POST /api/v1/coding/workspaces` | `HTTP 200` + `workspace.id` | `HTTP 200` + UUID | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-E02** | Cross-user workspace isolation | Users A & B | User B calls `GET /coding/workspaces/{ws_id}` | `HTTP 404` | `HTTP 404` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-E03** | Workspace file write, read & git diff | Owned workspace | Invoke `write_file`, `read_file`, `GET /diff` | All `HTTP 200` with exact content | `write=200`, `read=200`, `diff=200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-E04** | Workspace path traversal blocked | Owned workspace | `read_file` with `path="../../.env"` | Blocked by `WorkspaceSecurity` | Blocked (`"Path traversal detected"`) | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-E05** | Submit durable coding job | Owned workspace | `POST /coding/workspaces/{id}/tasks` (`title`, `objective`) | `HTTP 200`, `status="QUEUED"`, `taskId` | `HTTP 200`, `status=QUEUED`, `taskId` returned | `ENV-LOCAL-LIVE` | Live E05/E06 check | **PASS** |
| **UAT-E06** | Coding events replay & cancellation | Queued coding task | `GET /tasks/{taskId}/events?after_sequence=0` -> `POST /cancel` -> `GET /tasks/{taskId}` | `events=200`, `cancel=200`, `status=CANCELLED` | `events=200`, `cancel=200`, `status=CANCELLED` | `ENV-LOCAL-LIVE` | Live E05/E06 check | **PASS** |
| **UAT-E07** | Real Remote Docker Sandbox E2E & `0` Orphans | Docker Engine + PG15 + Redis + `sandbox-executor` + `coding-worker` | Full lifecycle: Coding API -> Worker -> Remote Executor -> Non-root `UID 1001` Container (`--network none`, HMAC capability) -> Cleanup | All assertions pass (`0` skips); `0` orphaned `sakura-exec-*` containers | Passed in CI Run `46167864598` (`Docker Sandbox E2E` & `Full-Stack E2E`); blocked on local Windows host because Docker Desktop daemon is stopped | `ENV-CI-LINUX` | CI Jobs `141049333807` & `141049333580` | **PASS (CI) / BLOCKED Locally** |
| **UAT-F01** | Allowed background task creation | Authenticated User A | `POST /api/v1/tasks` (`type="web_research"`) | `HTTP 200` | `HTTP 200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-F02** | Forged internal task rejected | Authenticated User A | `POST /api/v1/tasks` (`type="storage_delete"`) | `HTTP 400` | `HTTP 400` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-F03** | Scheduled task CRUD + IANA timezone + runs | Authenticated User A | `POST /scheduled` (`0 9 * * *`, `Asia/Kolkata`) -> `PUT` -> `GET /runs` -> `DELETE` | All `HTTP 200` | `create=200`, `put=200`, `runs=200`, `del=200` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-F04** | Multi-worker PG15 `SKIP LOCKED`, lease fencing & scheduler dedup | Real PostgreSQL 15 | Concurrency & lease-expiry regression tests | Zero double claims; stale workers fenced out | Passed (`0` skips) in CI Run `46167864598` | `ENV-CI-LINUX` | CI Job `141049333804` | **PASS (CI)** |

### H & UX. Security, Browser UX & Responsive Audit
| Test ID | Feature / Workflow | Preconditions | Test Procedure | Expected Outcome | Actual Observed Outcome | Environment | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **UAT-H01** | Malformed UUID rejection | Authenticated User A | `GET /conversations/not-a-uuid/messages` | `HTTP 400` | `HTTP 400` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-H02** | `/_next/image` disabled | Running Next.js (`images.unoptimized: true`) | `GET /_next/image?url=%2Ffavicon.ico&w=64&q=75` | `HTTP 404` | `HTTP 404` | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UAT-H03** | `/readiness` truthfulness & zero secret leak | Running FastAPI | `GET /readiness` | `HTTP 200`, revision `j9f7a263b56c`, zero secrets | `HTTP 200`, `DEGRADED` (`redis=UNAVAILABLE`), zero secrets | `ENV-LOCAL-LIVE` | Live UAT v2 | **PASS** |
| **UX-01..09** | Playwright Desktop (`1440×900`) & Mobile (`390×844`) UX | Running FE + BE | Unauth redirect (`/chat -> /login`), 7 public routes `200`, UI login, reload persistence, Library/Projects/Scheduled/Plugins views, `/console`, mobile overflow check, pageerrors | All routes & views work cleanly; `0` mobile overflow; `0` pageerrors | `18/18` functional/layout assertions PASSED; screenshots `05_library_view.png` & `06_mobile_chat.png` captured | `ENV-LOCAL-LIVE` | Playwright Chromium | **PASS** |
| **UX-10** | Dev-mode console error audit | Next.js `next dev` | Collect browser `console.error` during rapid automated navigation | Zero application runtime errors | Observed only 3 Next.js dev-mode `Abort fetching component for route` notices caused by rapid `page.goto()` cancelling in-flight dev prefetches; `0` application errors, `0` uncaught `pageerror`s | `ENV-LOCAL-LIVE` | Playwright Chromium | **PASS (Dev Prefetch Notice Noted)** |
