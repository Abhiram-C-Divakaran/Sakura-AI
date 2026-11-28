# Sakura AI — AI Conversation & Hybrid RAG Workflows

This document details the multi-provider conversational routing pipeline (`llm/router.py`, `llm/agent.py`) and the per-user Hybrid Retrieval-Augmented Generation pipeline (`rag/ingestion/parser.py`, `rag/embeddings/manager.py`, `rag/retrieval.py`).

---

## Diagram 4: AI Conversation & Multi-Provider Failover Workflow

```mermaid
flowchart TD
    Req["POST /api/v1/chat/stream\n(Bearer JWT, conversation_id, prompt, intent, intensity)"] --> Quota["Atomic Daily Quota Check\n(user_usage_quotas: chat <= 500/day)"]
    Quota -->|"Exceeded"| Q429["HTTP 429 Too Many Requests"]
    Quota -->|"OK"| LoadCtx["Load Scoped Context:\n1. Conversation History (messages)\n2. User Semantic Memories (user_memories)\n3. Optional Attached Docs & Hybrid RAG Chunks\n4. Optional Web Search (Tavily / DuckDuckGo)"]

    LoadCtx --> IntentCheck{"Intent == private_data\nor local_private?"}
    IntentCheck -->|"Yes (Strict Privacy Boundary)"| LocalOnly["Allowed Providers: [ollama] ONLY\nCloud Providers Prohibited"]
    LocalOnly -->|"Ollama Unconfigured"| FailPriv["Raise PrivateModelUnavailableError\n(Fail Closed — Zero Cloud Leakage)"]
    LocalOnly -->|"Ollama Ready"| StreamExec["Stream Tokens (Bounded Timeout)"]

    IntentCheck -->|"No (Standard Routing)"| Order["Intent-Based Provider Priority:\n- Coding: groq -> anthropic -> openai -> ollama\n- Reasoning/Docs: anthropic -> openai -> groq -> ollama\n- General: groq -> openai -> anthropic -> ollama"]
    Order --> TryProv["Invoke Primary Provider\n(HTTPX / SDK Bounded Timeout)"]
    TryProv -->|"Success"| StreamExec
    TryProv -->|"Transient Error\n(429, 5xx, Timeout, Network)"| Failover["Failover to Next Configured Provider"]
    TryProv -->|"Non-Transient Error\n(401, 403 Invalid Key)"| ErrOut["Return Transparent Error\n(No Silent Mock Fallback)"]
    Failover --> StreamExec

    StreamExec --> Persist["Persist Assistant Message (messages) +\nAsync Memory Extraction (user_memories)"]
    Persist --> SSEEnd["Emit SSE Done Event + Usage Metadata"]
```

*Figure 4: Conversational AI execution pipeline (`llm/router.py`, `llm/agent.py`) illustrating quota enforcement, context assembly, fail-closed private routing, and transient-only provider failover.*

---

## Diagram 5: Document Ingestion & Hybrid RAG (`pgvector` + Okapi BM25) Workflow

```mermaid
flowchart TB
    subgraph Ingestion["Asynchronous Ingestion Pipeline (services/documents.py & tasks/worker.py)"]
        Up["POST /api/v1/library/upload or /documents/upload\n(Quota: 100 files/day, MIME/size validation)"] --> StoreObj["Persist Raw File to StorageBackend\nKey: users/<user_id>/documents/<doc_id>/<filename>"]
        StoreObj --> CreateDoc["Insert documents Row\n(indexing_status='QUEUED', index_generation=N, deletion_status='ACTIVE')"]
        CreateDoc --> WorkerPick["Task Worker Claims Indexing Job\n(Lease-Fenced)"]
        WorkerPick --> Parse["DocumentParser (rag/ingestion/parser.py)\nPDF (pdfplumber), Markdown, TXT, Code\nWindow: 800 chars, 150-char overlap"]
        Parse --> EmbedCheck{"OPENAI_API_KEY\nConfigured?"}
        EmbedCheck -->|"Yes"| DenseGen["EmbeddingManager\nOpenAI text-embedding-3-small\n(1536 dimensions, 30s timeout)"]
        EmbedCheck -->|"No"| NullVec["embedding = NULL\n(Zero Fake/Random Vectors;\nHonest BM25 Fallback)"]
        DenseGen --> GenFence["Stale-Generation Guard:\nVerify documents.index_generation == N\nand deletion_status == 'ACTIVE'"]
        NullVec --> GenFence
        GenFence --> WriteChunks[("Insert document_chunks\n(PostgreSQL vector(1536) / SQLite JSON)\nUpdate indexing_status = 'READY'")]
    end

    subgraph Retrieval["Per-User Hybrid Retrieval Pipeline (rag/retrieval.py)"]
        Query["User Chat Query +\nOptional Knowledge-Base / File Scope"] --> ScopeSQL["Strict Tenant Filter:\nJOIN documents WHERE user_id = current_user.id\nAND deletion_status = 'ACTIVE'"]
        ScopeSQL --> DenseBranch["Dense Semantic Branch:\nPostgreSQL pgvector Cosine Distance (<=>)\n(Top-K chunks where embedding IS NOT NULL)"]
        ScopeSQL --> LexicalBranch["Lexical BM25 Branch:\nOkapi BM25 Scorer (k1=1.5, b=0.75)\nTokenized IDF + Length Normalization"]
        DenseBranch --> RRF["Reciprocal Rank Fusion (RRF)\nscore(d) = sum( 1 / (k + rank_i(d)) )"]
        LexicalBranch --> RRF
        RRF --> TopK["Top-K Grounded Context Chunks\nwith Source Filename Citations -> Prompt Context"]
    end

    WriteChunks -.->|"Queried by"| ScopeSQL
```

*Figure 5: End-to-end Document Intelligence and Hybrid RAG pipeline showing generation-fenced indexing, honest `NULL` embedding fallback when unconfigured, native `pgvector(1536)` cosine retrieval, Okapi BM25 lexical scoring, and Reciprocal Rank Fusion.*
