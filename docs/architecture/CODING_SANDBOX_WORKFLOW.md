# Sakura AI — Sakura Coding Engine & Docker Sandbox Isolation

This document details the durable execution lifecycle of **Sakura Code** (`coding/agent.py`, `coding/job_worker.py`, `coding/tools.py`) and the defense-in-depth container isolation enforced by `coding/sandbox.py`, `coding/sandbox_service.py`, `coding/capabilities.py`, and `anime-ai/sandbox/Dockerfile`.

---

## Diagram 8: Sakura Coding Engine Execution Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant User as Developer (Browser / Console)
    participant API as FastAPI Coding API (api/coding.py)
    participant DB as PostgreSQL 15 (coding_jobs & coding_task_events)
    participant Worker as Standalone Coding Worker (coding/job_worker.py)
    participant Agent as Sakura Coding Agent (coding/agent.py)
    participant Tools as CodingToolchain (coding/tools.py)
    participant Exec as Remote Sandbox Executor (:9000)

    User->>API: POST /api/v1/coding/workspaces/{id}/tasks (Bearer JWT, instructions, intensity)
    API->>DB: Enforce coding_task quota (50/day), verify workspace owner, insert coding_jobs (QUEUED)
    API-->>User: HTTP 200 { job_id, task_id, status: "QUEUED" }

    User->>API: GET /api/v1/coding/tasks/{task_id}/events/stream (SSE, optional after_sequence)
    Worker->>DB: Atomic claim (FOR UPDATE SKIP LOCKED) + acquire lease (worker_id, execution_attempt_id)
    Worker->>Agent: Start repository-level coding loop

    loop Iterative Plan -> Inspect -> Edit -> Verify Loop
        Agent->>Tools: Invoke tool (read_file, search_code, apply_patch, git_diff, run_tests, run_command)
        Tools->>Tools: WorkspaceSecurity path-traversal & symlink containment check
        alt Shell / Test / Build Command
            Tools->>Exec: POST /execute (X-Sandbox-Token, workspace_id, command, optional HMAC capability)
            Exec-->>Tools: { exit_code, stdout (bounded), stderr (bounded), duration_ms }
        end
        Agent->>DB: Append sequential coding_task_events (sequence_number++)
        DB-->>API: Replay / stream structured phase, tool, diff & verification events
        API-->>User: Live SSE Event (CodingActivity, DiffViewer, VerificationSummary)
        Worker->>DB: Renew lease heartbeat & check cancel_requested flag
    end

    Worker->>DB: Fenced Conditional Terminal Update (WHERE id=? AND execution_attempt_id=? AND lease_expires_at > NOW())
    Worker-->>User: Final verification summary & unified Git diff
```

*Figure 8: End-to-end Sakura Coding Engine lifecycle demonstrating durable queueing, sequential event persistence for lossless SSE replay, iterative tool invocation, and fenced terminal writes.*

---

## Diagram 9: Docker Sandbox Isolation & Capability Security Boundary

```mermaid
flowchart TB
    subgraph AppHost["Application / Worker Network (ZERO /var/run/docker.sock Access)"]
        API["FastAPI Backend (:8000)\nMints Single-Use HMAC Capability\n(coding/capabilities.py)"]
        CW["Coding Worker\n(coding/job_worker.py)\nAllowlists Child Env Vars"]
    end

    subgraph AuthGate["Sandbox Executor Security Gate (coding/sandbox_service.py :9000)"]
        Tok["1. Constant-Time Check:\nX-Sandbox-Token == SAKURA_SANDBOX_SERVICE_TOKEN"]
        UUID["2. Strict Workspace UUID Validation\n(Rejects traversal, symlinks, '..')"]
        NetGate{"3. Outbound Network\nRequested?"}
        CapVerify["Verify HMAC-SHA256 Signature,\nWorkspace ID, Exact Command Hash,\nExpiry TTL, & Consume Single-Use Nonce in Redis"]
        DenyNet["Block Execution (HTTP 403)\nFail-Closed if Redis Down"]
    end

    subgraph DockerHost["Hardened Ephemeral Container Execution (anime-ai/sandbox/Dockerfile)"]
        RunCmd["docker run --rm --name sakura-exec-<id>\n--user 1001:1001 (Non-Root)\n--cap-drop ALL\n--security-opt no-new-privileges:true\n--cpus=2.0 --memory=512m --pids-limit=64"]
        NetNone["Default: --network none\n(Zero Egress / No Metadata SSRF)"]
        NetBridge["Approved Only: --network bridge\n(Single Command, Nonce Consumed)"]
        Mount["Bind Mount ONLY:\n/workspaces/<workspace_uuid>:/workspace:rw\n(Sibling workspaces invisible)"]
        Cleanup["Timeout / Cancel Watchdog:\ndocker kill -> docker rm -f\n(Verified 0 orphaned containers in CI)"]
    end

    CW -->|"HTTP POST /execute"| Tok
    API -.->|"Signed Capability Token\n(on explicit user approval)"| CW
    Tok --> UUID
    UUID --> NetGate
    NetGate -->|"No (Default)"| RunCmd
    RunCmd --> NetNone
    NetGate -->|"Yes"| CapVerify
    CapVerify -->|"Invalid / Replayed / Redis Down"| DenyNet
    CapVerify -->|"Valid Single-Use Token"| RunCmd
    RunCmd --> NetBridge
    RunCmd --> Mount
    RunCmd --> Cleanup
```

*Figure 9: Defense-in-depth Docker sandbox isolation showing socket isolation, non-root execution (`UID 1001:1001`), default `--network none`, resource limits (`2.0` CPUs, `512 MB` RAM, `64` PIDs), single-workspace mounting, and single-use HMAC capability gating.*
