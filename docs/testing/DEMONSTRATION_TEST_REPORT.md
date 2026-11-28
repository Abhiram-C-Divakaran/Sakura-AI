# Sakura AI — Demonstration Readiness & Phase 3 Test Report

**Prepared:** 2026-11-28  
**Branch:** `hardening/outbox-pgvector-staging-readiness`  
**Verified CI Run:** [`46167864598`](https://github.com/Abhiram-C-Divakaran/Sakura-AI/actions/runs/46167864598) on `03e213d` (**4/4 Required Jobs PASSED**)

---

## 1. Phase 2 Discrepancy Closure & Slide QA

Before executing live UAT, every Phase 2 artifact was audited directly against the codebase and latest CI:
1. **PPTX Geometric Overflow Fix (Confirmed Defect Fixed):** Programmatic bounding-box inspection of all 19 slides in `presentation/Sakura_AI_Academic_Presentation.pptx` detected that Slide 8's embedded `arch_overview.png` (`width=12.23 in` -> `height=6.27 in` starting at `y=1.32 in`) overflowed the `7.50 in` slide bottom (`7.59 in`), and Slides 11–12 sat tight against the `7.12 in` footer. Updated `presentation/build_presentation.py` to size Slides 8, 11, and 12 by bounded `height` (`5.60 in` / `5.55 in`) centered horizontally, rebuilt the `.pptx`, and re-verified **`PPTX_SLIDES: 19, OUT_OF_BOUNDS: []`**.
2. **CI Reference Synchronization:** Updated all Phase 2 references from CI Run `46157049085` (`d8de865`) to the latest verified Run `46167864598` (`03e213d`) across `README.md`, `docs/academic/PROJECT_REPORT.md`, `docs/academic/TESTING_DOCUMENTATION.md`, `docs/interview/VIVA_QUESTIONS_AND_ANSWERS.md`, `presentation/SLIDES_SOURCE.md`, and `presentation/build_presentation.py`.
3. **Screenshot Freshness & Coverage:** Verified all 4 existing screenshots (`01_landing.png`, `02_login.png`, `03_chat_workspace.png`, `04_api_docs.png`) and added 2 new live captures from Playwright Chromium UX testing: [`05_library_view.png`](../assets/screenshots/05_library_view.png) and [`06_mobile_chat.png`](../assets/screenshots/06_mobile_chat.png).
4. **Placeholder Integrity:** Preserved all student/institution/guide placeholders intact (`[Student Name]`, `[Roll Number]`, etc.) without fabricating personal details.

---

## 2. Live Demonstration Reliability Verification

| Readiness Check | Verification Method | Observed Result |
| --- | --- | --- |
| **Pre-Flight Script (`docs/demo_assets/preflight_check.py`)** | Executed live against `127.0.0.1:8000` & `127.0.0.1:3000` | **9/9 PASS — `READY FOR DEMO`** |
| **Restart Persistence** | Seeded isolated user + conversation + uploaded file (`PERSIST_CANARY_8821`), terminated & restarted `uvicorn`, re-authenticated and downloaded both | **`conv_ok=True`, `file_ok=True`, `cleanup=200` (PASS)** |
| **Live AI Streaming** | Sent live prompt over `/api/v1/chat/stream` against configured Groq adapter | **PASS** (`425` bytes streamed live + 2 persisted messages) |
| **Canary RAG Retrieval** | Parsed `docs/demo_assets/sample_knowledge_base.md` and ran Okapi BM25 query for unique synthetic facts (`7741`, `Sapphire-7`) | **PASS** (3 chunks, score `3.609`, both canary facts retrieved in top chunk) |
| **Desktop (`1440×900`) & Mobile (`390×844`) UX** | Playwright Chromium audit across public routes, auth redirect, reload persistence, Library/Projects/Scheduled/Plugins, `/console` | **PASS** (`0` uncaught pageerrors, `0` horizontal mobile overflow) |
| **Live WebSocket Single-Use Ticket** | Connected via `websockets` to `/api/v1/ws?ticket=...`, then attempted replay | **PASS** (`first_connect=True`, `replay_rejected=True`) |
| **Multi-Tenant & Security Boundaries** | Cross-user `404` (chat, library, workspace), `?token=` `401`, forged task `400`, path traversal blocked, `/_next/image` `404` | **PASS** (100% enforced live) |

---

## 3. Demonstration Readiness Verdict

- **5-Minute Short Demonstration (`docs/DEMO_PLAYBOOK.md` Section 2):** **READY.** Pre-flight script, live UI, Groq streaming, sample canary document, and architecture slides are verified and repeatable in under 5 minutes.
- **15-Minute Full Demonstration (`docs/DEMO_PLAYBOOK.md` Section 3):** **READY (with documented local-vs-CI split for Docker/PG15/SMTP/Whisper).** On a local Windows laptop without Docker Desktop running, demonstrate live chat, auth, library, BM25 RAG, image job idempotency, scheduled tasks, and coding workspace tools locally, and present GitHub Actions Run [`46167864598`](https://github.com/Abhiram-C-Divakaran/Sakura-AI/actions/runs/46167864598) for real PostgreSQL 15 `pgvector` and non-root Docker sandbox execution (or start Docker Desktop to run the full Compose topology locally).
