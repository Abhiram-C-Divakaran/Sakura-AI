# Sakura AI — Security & Abuse Protection Verification Report

Every control below is verified against actual implementation files, automated regression tests, live Phase 3 UAT against `http://127.0.0.1:8000` & `http://127.0.0.1:3000`, and GitHub Actions CI Run [`46167864598`](https://github.com/Abhiram-C-Divakaran/Sakura-AI/actions/runs/46167864598) on commit `03e213d`.

---

## 1. Security Verification Matrix

| ID | Security Control | Expected Behavior | Observed Result & Evidence | Environment | Status |
| --- | --- | --- | --- | --- | --- |
| **SEC-01** | Password complexity & hashing (`auth/manager.py`) | Reject weak passwords (`< 8` chars); hash via Passlib `pbkdf2_sha256` | `UAT-A01`: weak password `"123"` rejected with `HTTP 400`; `test_auth_security.py` passed | Local Live + CI | **PASS** |
| **SEC-02** | `PyJWT` (`HS256`) & tamper rejection | `AuthManager` uses `PyJWT` (zero `python-jose` imports); tampered tokens rejected `401` | `UAT-A06`: tampered token -> `HTTP 401`; `test_auth_manager_uses_pyjwt_and_rejects_tampered_tokens` passed | Local Live + CI | **PASS** |
| **SEC-03** | Unauthenticated API access rejection | Protected endpoints refuse requests without Bearer token (`401`) | `UAT-A05`: `GET /api/v1/conversations` without header -> `HTTP 401`; browser `/chat` -> redirects to `/login` | Local Live + Browser | **PASS** |
| **SEC-04** | Header-only file downloads (No JWTs in URLs) | `?token=` query string rejected with `401`; `Authorization: Bearer` succeeds `200` | `UAT-C03` (`200`), `UAT-C04` (`?token=` -> `HTTP 401`) | Local Live + CI | **PASS** |
| **SEC-05** | Single-use WebSocket ticket authentication | Ticket works once for WS upgrade; replay attempt rejected | `UAT-A07`: live WS `first_connect=True`, `replay_rejected=True`; `test_ws_ticket.py` passed | Local Live + CI | **PASS** |
| **SEC-06** | Multi-tenant resource isolation (IDOR) | Cross-user access to conversations, files, and coding workspaces returns `404` | `UAT-B08` (`404`), `UAT-C05` (`404`), `UAT-E02` (`404`) | Local Live + CI | **PASS** |
| **SEC-07** | Malformed UUID input validation | Non-UUID resource identifiers fail cleanly with `HTTP 400` (never `500`) | `UAT-H01`: `/conversations/not-a-uuid/messages` -> `HTTP 400`; `test_workspace_topology_e2e.py` passed | Local Live + CI | **PASS** |
| **SEC-08** | Forged internal task prevention | Public `POST /api/v1/tasks` rejects `storage_delete` and non-allowlisted types (`400`) | `UAT-F02`: `type="storage_delete"` -> `HTTP 400` | Local Live + CI | **PASS** |
| **SEC-09** | Workspace path traversal prevention | `../../.env` and symlink escapes blocked by `WorkspaceSecurity` | `UAT-E04`: blocked (`"Path traversal detected: '../../.env' escapes workspace root"`) | Local Live + CI | **PASS** |
| **SEC-10** | Fail-closed private LLM routing | `local_private` / `private_data` intents never fall back to cloud providers (`Groq`/`OpenAI`) | Verified `LLMRouter().get_ordered_providers('local_private') == []` even with active `GROQ_API_KEY` | Local Unit + CI | **PASS** |
| **SEC-11** | Daily per-user usage quotas | Atomic UTC-day caps (`chat: 500`, `image: 50`, `coding: 50`, `upload: 100`, `scheduled: 30`) enforced | `UAT-A08`: `GET /api/v1/auth/me/quotas` returns live counters; quota exhaustion `429` verified in unit suite | Local Live + CI | **PASS** |
| **SEC-12** | Fail-closed Redis rate limiting & CIDR proxy parsing | In production, Redis outage on auth rate limits returns `HTTP 503`; `X-Forwarded-For` trusts only `TRUSTED_PROXY_CIDRS` | Verified in `test_fail_closed_security_regression.py` (`22/22` tests pass in local & CI) | Local Unit + CI | **PASS** |
| **SEC-13** | Production startup secret guards & zero leakage | Production startup refuses weak/default/reused secrets; `/readiness` never exposes secrets | `UAT-H03`: `/readiness` clean (`j9f7a263b56c`, zero secret strings); `validate_env.py` & `test_auth_security.py` pass | Local Live + CI | **PASS** |
| **SEC-14** | Next.js `/_next/image` mitigation | Unused Next.js image optimizer disabled via `images: { unoptimized: true }` | `UAT-H02`: `GET /_next/image?url=/favicon.ico&w=64&q=75` -> `HTTP 404` | Local Live + CI | **PASS** |
| **SEC-15** | Docker sandbox non-root, network & secret isolation | Separate `sandbox-executor` (`:9000`); child runs `UID 1001`, `--network none`, `--cap-drop ALL`, `2 CPU/512 MB/64 PIDs`, allowlisted env, single-use HMAC capability, `0` orphans | CI Run `46167864598` (`Docker Sandbox E2E Integration` & `Full-Stack Integration Tests` both `success`, `0` orphaned containers) | CI Ubuntu Linux (Local Docker stopped -> `BLOCKED` locally) | **PASS (CI)** |
| **SEC-16** | Account deletion & credential invalidation | `DELETE /api/v1/auth/me` requires password + `"DELETE"`, purges user, invalidates future login, preserves `account_audit_events` | `UAT-A11-A/B`: `DELETE` -> `200`, subsequent login -> `400`; `test_postgres_pgvector_and_concurrency.py` verifies audit row | Local Live + CI | **PASS** |

---

## 2. Outstanding Security Recommendations (Tracked Honestly)
1. **Next.js `14.2.35` -> `16.x` (React 19) Upgrade:** Planned as a dedicated post-merge PR to clear upstream `npm audit --omit=dev` advisories (`next`, `postcss`, `source-map-js`) beyond the current `/_next/image` mitigation.
2. **Automated CI Supply-Chain Scans:** Add `pip-audit` and `npm audit --audit-level=high` jobs to `.github/workflows/ci.yml`.
3. **External Staging Isolation:** Deploy `sandbox-executor` on a dedicated hardened host/VM (or gVisor/Firecracker microVM) with IMDSv2 / metadata egress rules before opening public internet signups.
