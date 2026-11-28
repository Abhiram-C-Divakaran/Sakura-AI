# Sakura AI — Overall System Architecture

This document defines the implemented high-level architecture and production deployment topology of **Sakura AI**, grounded directly in `anime-ai/docker-compose.prod.yml`, `anime-ai/ops/nginx.conf.example`, and `anime-ai/backend/main.py`.

---

## Diagram 1: Overall Sakura AI System Architecture

```mermaid
flowchart TB
    subgraph Client["Client Tier (Browser)"]
        UI["Next.js 14 SPA / SSR Pages\n(/, /login, /chat, /console, /share/[token])"]
        Hooks["Realtime Hooks\n(useRealtime WS, useTasks, useCodingTaskStream SSE)"]
        UI --> Hooks
    end

    subgraph Edge["Edge / Reverse Proxy Tier"]
        Nginx["Nginx TLS 1.2/1.3 Reverse Proxy\n(HSTS, Rate-Limit Headers, Unbuffered SSE, WS Upgrade)"]
    end

    subgraph AppTier["Application Tier"]
        FE["Next.js Frontend Server (:3000)\n(images.unoptimized=true, API Rewrites)"]
        API["FastAPI Backend API (:8000)\n(auth, chat, library, coding, images, tasks, audio, projects)"]
    end

    subgraph Workers["Dedicated Durable Worker Processes (No Embedded Workers in Prod)"]
        W1["Task Worker (tasks/worker.py)\nDocs, Summaries, Exports, Storage Outbox"]
        W2["Image Worker (media/image_worker.py)\nRaster Gen, Idempotent Variations"]
        W3["Coding Worker (coding/job_worker.py)\n21-Tool Autonomous Coding Agent"]
        Sched["Cron Scheduler (tasks/scheduler.py)\nIANA Timezone-Aware Dispatch"]
    end

    subgraph SandboxTier["Isolated Execution Boundary (Separate Host / Socket Boundary)"]
        Exec["Remote Sandbox Executor (:9000)\n(coding/sandbox_service.py)\nSole Host with /var/run/docker.sock"]
        Child["Ephemeral Non-Root Container\n(sakura-sandbox, UID 1001:1001,\n--network none, --cap-drop ALL)"]
    end

    subgraph DataTier["Stateful Data & Storage Tier"]
        PG[("PostgreSQL 15 + pgvector\n32 ORM Tables, vector(1536),\nFOR UPDATE SKIP LOCKED")]
        Redis[("Redis 7 (AOF + noeviction)\nRate Limits, Pub/Sub, Wakeups,\nCapability Nonces")]
        Obj[("Object Storage\nS3-Compatible / Local FS\nusers/<user_id>/...")]
    end

    subgraph ExternalAI["External AI & Media Providers"]
        LLMs["LLM Providers\n(Groq, OpenAI, Anthropic, Local Ollama)"]
        Embed["OpenAI Embeddings\n(text-embedding-3-small, 1536-d)"]
        MediaExt["Pollinations Raster / OpenAI Whisper / Tavily Search"]
    end

    UI -->|"HTTPS / WSS"| Nginx
    Nginx -->|"/ (SSR / Static)"| FE
    Nginx -->|"/api/* & /api/v1/ws"| API

    API --> PG
    API --> Redis
    API --> Obj
    API --> LLMs
    API --> MediaExt

    Redis -.->|"List Wakeups & Pub/Sub"| W1
    Redis -.->|"Wakeup"| W2
    Redis -.->|"Wakeup"| W3
    W1 -.->|"WS Events via Pub/Sub"| Redis
    W2 -.->|"WS Events via Pub/Sub"| Redis
    W3 -.->|"WS Events via Pub/Sub"| Redis

    W1 --> PG
    W1 --> Obj
    W1 --> Embed
    W2 --> PG
    W2 --> Obj
    W2 --> MediaExt
    Sched --> PG
    W3 --> PG
    W3 --> LLMs
    W3 -->|"X-Sandbox-Token +\nSingle-Use HMAC Capability"| Exec
    Exec -->|"docker run --rm\nSingle Workspace Bind Mount"| Child
```

*Figure 1: Overall 10-service Sakura AI architecture showing strict separation between the stateless API, four independent worker processes, PostgreSQL 15 + `pgvector` authoritative state, Redis 7 coordination, and the isolated Docker sandbox execution boundary.*

---

## Service Responsibilities (`anime-ai/docker-compose.prod.yml`)

| Service | Entrypoint / Image | Primary Responsibility | Network / Security Boundary |
| --- | --- | --- | --- |
| `nginx` | `nginx.conf.example` | TLS termination, security headers, SSE proxy buffering off, WebSocket upgrade | Public edge; sets `X-Forwarded-For` trusted via `TRUSTED_PROXY_CIDRS` |
| `frontend` | `anime-ai/frontend/Dockerfile` | Next.js 14 React UI (`:3000`), `images.unoptimized=true` | Internal app network; no DB or Redis access |
| `backend` | `uvicorn main:app` (`:8000`) | REST APIs, SSE chat streaming, WebSocket hub, `/health` & `/readiness` | No Docker socket; fail-closed production startup guards |
| `worker` | `python -m tasks.worker` | Document parsing/embedding, scheduled runs, ZIP exports, storage deletion outbox | Lease-fenced DB claims + killable subprocess storage delete runner |
| `image-worker` | `python -m media.image_worker` | Raster image generation, prompt-context variations, library sync | Lease-fenced claims, idempotency key deduplication |
| `coding-worker` | `python -m coding.job_worker` | Autonomous repository coding loop & tool invocation | Calls `sandbox-executor` over HTTP; zero Docker socket access |
| `scheduler` | `python -m tasks.scheduler` | Polls `scheduled_tasks` with cron + IANA timezone evaluation | Enforces unique `(task_id, scheduled_for)` occurrence constraint |
| `sandbox-executor` | `python -m coding.sandbox_service` (`:9000`) | Sole service mounting `/var/run/docker.sock`; spawns non-root child containers | Requires `X-Sandbox-Token` + single-use HMAC capability for network commands |
| `postgres` | `pgvector/pgvector:pg15` | Authoritative relational + `vector(1536)` store (32 tables) | Internal network only; backed up via `backup_postgres.sh` |
| `redis` | `redis:7-alpine` (AOF, `noeviction`) | Rate limiting, worker wakeups, WS Pub/Sub, single-use capability nonces | Internal network only; fail-closed in production |
