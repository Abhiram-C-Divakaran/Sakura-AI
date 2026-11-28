# Sakura AI — Feature Verification Matrix

Maps every major documented capability against actual verified behavior across local live execution, unit/regression suites, and GitHub Actions CI Run [`46167864598`](https://github.com/Abhiram-C-Divakaran/Sakura-AI/actions/runs/46167864598).

| Feature / Module | Local Live Dev (SQLite + Groq) | Automated Unit & Regression | GitHub Actions CI (PG15 + Redis + Docker + Playwright) | Overall Verification Status | Notes / Honest Boundaries |
| --- | --- | --- | --- | --- | --- |
| **Auth (`PyJWT` HS256, Register, Login, Quotas)** | **PASS** (`UAT-A01..A08`) | **PASS** | **PASS** | **Verified** | Migrated from `python-jose` to `PyJWT` in Phase 1 |
| **WebSocket Single-Use Tickets & Replay Block** | **PASS** (`UAT-A07` live WS) | **PASS** (`test_ws_ticket.py`) | **PASS** | **Verified** | Real WS handshake succeeded once; replay rejected |
| **Self-Service Account Export & Deletion** | **PASS** (`UAT-A09`, `A11`) | **PASS** | **PASS** | **Verified** | Tested strictly on isolated ephemeral accounts |
| **SMTP Password Reset Delivery** | **BLOCKED** (`503` fail-closed; no local SMTP) | **PASS** (token hashing/consumption) | **PASS** (unit) | **Blocked (External SMTP)** | Endpoint truthfully returns `503` when SMTP/HTTPS URL unconfigured |
| **Streaming AI Chat (Groq SSE) & Persistence** | **PASS** (`UAT-B01..B03`) | **PASS** | **PASS** | **Verified** | Real Groq tokens streamed live & persisted to DB |
| **Search, Pin, Archive, Share & Feedback** | **PASS** (`UAT-B04..B07`) | **PASS** | **PASS** | **Verified** | Share link public read (`200`) & revocation (`404`) verified live |
| **Fail-Closed Private Routing (`Ollama`)** | **BLOCKED** (no local Ollama; fail-closed verified `[]`) | **PASS** | **PASS** | **Verified (Fail-Closed)** | Never leaks `local_private` intent to cloud Groq |
| **Document Upload (`PDF`, `MD`, `TXT`), Preview, Download** | **PASS** (`UAT-C01..C05`, `G01`) | **PASS** | **PASS** | **Verified** | Header-only Bearer auth; `?token=` rejected `401` |
| **Document Parsing & Okapi BM25 Canary Retrieval** | **PASS** (`3` chunks, score `3.609`, hits `7741` & `Sapphire-7`) | **PASS** | **PASS** | **Verified** | Unique synthetic facts retrieved accurately without embeddings |
| **Native PostgreSQL `pgvector(1536)` + Hybrid RRF** | **BLOCKED** (SQLite locally, `OPENAI_API_KEY` unset) | **PASS** (SQLite JSON fallback) | **PASS** (`0` skips on PG15) | **Verified (CI PG15)** | Real `pgvector/pgvector:pg15` verified in CI `46167864598` |
| **Async Document Deletion (`StorageDeletionOutbox`)** | **PASS** (`202` + `DELETING`) | **PASS** | **PASS** (PG15 outbox fencing) | **Verified** | Killable subprocess runner verified in regression suite & CI |
| **Durable Image Jobs & Idempotency Replay** | **PASS** (`UAT-D01..D03` exact same `job_id`) | **PASS** (`400`/`202`/`409`) | **PASS** | **Verified** | Variation fingerprint mismatch `409` verified in PG15 CI |
| **Pixel-Mask Image Inpainting / True Super-Resolution** | **NOT IMPLEMENTED** | **NOT IMPLEMENTED** | **NOT IMPLEMENTED** | **Not Implemented** | Truthfully reported as `false` by `/api/v1/capabilities` |
| **Audio Upload Validation & Whisper STT** | Validation **PASS** (`400`); Live STT **BLOCKED** (`503`, no `OPENAI_API_KEY`) | **PASS** | **PASS** | **Blocked (External Key)** | Clean `503` configuration error when unconfigured |
| **Sakura Coding Workspaces, Tools & Path Guards** | **PASS** (`UAT-E01..E06`) | **PASS** | **PASS** | **Verified** | File write/read/diff, traversal guard, task events & cancel verified |
| **Remote Docker Sandbox Isolation (`UID 1001`, `--network none`)** | **BLOCKED** (Docker Desktop stopped on Windows) | **PASS** (mocked/policy) | **PASS** (real Docker, `0` orphans) | **Verified (CI Docker)** | Proven in CI `Docker Sandbox E2E Integration` & `Full-Stack Integration Tests` |
| **Scheduled Tasks (Cron + IANA Timezones) & Workers** | **PASS** (`UAT-F01..F03`) | **PASS** | **PASS** (PG15 `SKIP LOCKED`) | **Verified** | Forged `storage_delete` blocked `400`; lease fencing proven in CI |
| **Third-Party Connectors (GitHub vs. Others)** | GitHub **Implemented**; Drive/Notion/Slack/Jira/PG **NOT IMPLEMENTED** (`501`) | **PASS** | **PASS** | **Partial (Honest 501)** | Non-GitHub connectors intentionally return `HTTP 501` |
| **Frontend UX, Auth Redirects & Mobile (`390×844`)** | **PASS** (Playwright desktop + mobile, `0` pageerrors, `0` overflow) | **PASS** (`tsc`, `lint`, `build`) | **PASS** (Playwright E2E) | **Verified** | Confirmed via live Playwright Chromium audit |
| **PostgreSQL 15 Backup & Restore (`pg_dump`/`pg_restore`)** | **BLOCKED** (no local `psql`) | N/A | **PASS** (positive + tampered `.sha256`) | **Verified (CI PG15)** | Official `postgres:15` client verified in CI `46167864598` |
