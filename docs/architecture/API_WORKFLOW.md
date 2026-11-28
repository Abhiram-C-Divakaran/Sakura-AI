# Sakura AI — API Communication, Authentication & Background Job Workflows

This document covers frontend-backend communication, authentication and WebSocket session security, and the database-authoritative durable worker + outbox lease-fencing architecture.

---

## Diagram 2: Frontend and Backend Communication

```mermaid
sequenceDiagram
    autonumber
    participant Browser as Browser (Next.js React App)
    participant AuthFetch as frontend/lib/api.ts (authFetch)
    participant Proxy as Nginx / Next.js Rewrite Proxy
    participant API as FastAPI Backend (:8000)
    participant MW as Correlation & Latency Middleware
    participant RL as Redis Sliding-Window Rate Limiter
    participant DB as PostgreSQL 15 / SQLite
    participant Redis as Redis 7 Pub/Sub

    Note over Browser,API: 1. Standard Authenticated REST Call
    Browser->>AuthFetch: Request /api/v1/conversations or /api/v1/library/files/{id}/download
    AuthFetch->>Proxy: HTTP Request + Authorization: Bearer <PyJWT>
    Proxy->>API: Forward + X-Forwarded-For (validated against TRUSTED_PROXY_CIDRS)
    API->>MW: Assign/Propagate X-Request-ID & Start Latency Timer
    MW->>RL: Check rate limit bucket (Fail-closed 503 if Redis down in prod)
    RL-->>MW: Allowed (or HTTP 429)
    MW->>API: Route Handler + AuthManager.get_current_user() + Ownership Guard
    API->>DB: Scoped query (WHERE user_id = current_user.id)
    DB-->>API: Owned records (or 404 on cross-tenant mismatch)
    API-->>Browser: JSON / Blob Stream + X-Request-ID Header

    Note over Browser,API: 2. Server-Sent Events (SSE) Streaming (Chat & Coding Activity)
    Browser->>Proxy: POST /api/v1/chat/stream (or GET /api/v1/coding/tasks/{id}/events/stream)
    Proxy->>API: Proxy with X-Accel-Buffering: no
    API-->>Browser: text/event-stream incremental chunks + completion metadata

    Note over Browser,Redis: 3. Real-Time Multi-Worker WebSocket Notifications
    Browser->>API: POST /api/v1/auth/ws-ticket (Bearer Header)
    API->>DB: Insert single-use ticket (websocket_tickets, 60s TTL)
    API-->>Browser: { "ticket": "<opaque-token>" }
    Browser->>API: WS Connect /api/v1/ws?ticket=<opaque-token>
    API->>DB: Atomically mark consumed_at = NOW() (rejects replay)
    API->>Redis: Subscribe user channel (ws:user:<user_id>)
    Redis-->>API: Worker progress/completion broadcast
    API-->>Browser: JSON event frame (task_update, image_ready, doc_indexed)
```

*Figure 2: Frontend-to-backend communication patterns across REST (`authFetch` with header-only Bearer auth), unbuffered SSE streaming, and ticket-authenticated multi-worker WebSockets.*

---

## Diagram 3: Authentication, Password Reset & Account Lifecycle Workflow

```mermaid
flowchart TD
    Start["Client Request"] --> AuthChoice{"Authentication Flow"}

    AuthChoice -->|"POST /api/v1/auth/register"| RegRL["Redis Rate Limit\n(Fail-closed 503 in prod)"]
    RegRL --> PwCheck["Validate Password Strength\n(>= 8 chars, complexity)"]
    PwCheck --> Hash["Hash via Passlib\npbkdf2_sha256"]
    Hash --> InsertUser[("Insert users row\n(UUID PK, unique username/email)")]

    AuthChoice -->|"POST /api/v1/auth/token"| LoginRL["Redis Rate Limit"]
    LoginRL --> VerifyPw["Verify pbkdf2_sha256 Hash\n(auth/manager.py)"]
    VerifyPw -->|"Invalid"| Err401["HTTP 400 / 401\nGeneric Error"]
    VerifyPw -->|"Valid"| MintJWT["Mint PyJWT HS256 Token\n(sub, exp, verified secret >= 32 chars in prod)"]
    MintJWT --> ClientStore["Client stores token;\nsends ONLY in Authorization: Bearer header"]

    AuthChoice -->|"GET /api/v1/library/files/{id}/download"| HeaderOnly{"Authorization Header Present?"}
    HeaderOnly -->|"Query ?token= Only"| Reject401["HTTP 401 Rejected\n(Zero JWTs in URLs/Logs)"]
    HeaderOnly -->|"Valid Bearer JWT"| OwnCheck["Verify document.user_id == current_user.id\n(404 on mismatch)"]

    AuthChoice -->|"POST /api/v1/auth/password-reset/request"| ResetTok["Generate CSPRNG Token;\nStore SHA-256 hash in password_reset_tokens"]
    ResetTok --> SMTP["Send SMTP Reset Email\n(services/email.py)"]
    SMTP --> ConfirmReset["POST /password-reset/confirm\nAtomic single-use consumption + hash update"]

    AuthChoice -->|"DELETE /api/v1/auth/me"| DelConfirm["Verify current password +\nconfirm == 'DELETE'"]
    DelConfirm --> Purge["Cancel active jobs, enqueue/purge storage objects,\ndelete user cascade, write account_audit_events"]
```

*Figure 3: Authentication architecture (`anime-ai/backend/auth/manager.py`, `auth/authorization.py`, `services/account.py`) illustrating `PyJWT` `HS256` signing, header-only file authentication, single-use password reset tokens, and self-service account deletion.*

---

## Diagram 7: Durable Background Job & Storage Deletion Outbox Processing

```mermaid
flowchart LR
    API["FastAPI API Endpoint\n(Upload / Delete / Image / Task)"] -->|"1. Transactional Commit"| PG[("PostgreSQL 15\nbackground_tasks /\nimage_generation_jobs /\nstorage_deletion_outbox")]
    API -.->|"2. Best-Effort Wakeup"| Redis[("Redis 7 List")]

    subgraph WorkerLoop["Standalone Worker Process (worker / image-worker)"]
        Poll["Hybrid Wakeup:\nRedis BLPOP + DB Poll Fallback"] --> Claim["Atomic Claim:\nPostgreSQL FOR UPDATE SKIP LOCKED\n(or CAS UPDATE WHERE status='PENDING' / expired lease)"]
        Claim --> Fence["Assign worker_id +\nexecution_attempt_id / claim_token +\nlease_expires_at"]
        Fence --> Heartbeat["Periodic Lease Heartbeat\n(Extends lease_expires_at only if token matches)"]
        Fence --> ExecWork{"Work Type"}
        ExecWork -->|"Document Index"| ParseEmbed["Parse PDF/MD/TXT -> Chunk -> Embed\nVerify index_generation fence"]
        ExecWork -->|"Storage Outbox"| Subproc["Killable Subprocess Runner\n(storage_delete_runner.py)\nBounded timeout -> SIGKILL on hang"]
        ExecWork -->|"Image Job"| GenImg["Pollinations Raster Pipeline\n+ QualityEvaluator + Storage Save"]
        ParseEmbed --> CondCommit["Fenced Conditional Terminal Write\nWHERE id=? AND attempt_id=? AND lease_expires_at > NOW()"]
        Subproc --> CondCommit
        GenImg --> CondCommit
    end

    PG --> Claim
    Redis -.-> Poll
    CondCommit -->|"Rows Affected == 1"| Done["COMPLETED / FAILED\n+ Publish WS Event via Redis Pub/Sub"]
    CondCommit -->|"Rows Affected == 0\n(Stale Worker Fenced Out)"| Abort["Discard Result;\nPrevent Split-Brain Overwrite"]
```

*Figure 7: Database-authoritative durable worker and outbox lease-fencing architecture preventing duplicate execution, split-brain terminal writes after lease expiry, and hung S3/storage deletion calls.*
