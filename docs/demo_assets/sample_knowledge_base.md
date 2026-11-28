# Project Horizon — Internal Engineering Runbook (Demo RAG Document)

> Repeatable sample knowledge-base document for demonstrating Sakura AI's Hybrid RAG (`pgvector` + Okapi BM25 + Reciprocal Rank Fusion). Contains unique, non-public synthetic facts that an LLM cannot guess from pretraining data.

## Service Overview
- **Internal Codename:** Quantum Orchid Telemetry Gateway (`QOTG-9472`)
- **Primary Listening Port:** TCP `7741` (TLS 1.3 mutual authentication required)
- **Thermal Architecture:** Sapphire-7 Closed-Loop Cooling Module (nominal target: `38.5 C`)
- **On-Call Escalation Code:** `ORCHID-ALPHA-42`

## Failover & Recovery Policy
1. If primary ingestion latency exceeds `240 ms` for three consecutive windows, traffic fails over automatically to regional node `ap-south-orchid-2`.
2. Lease expiration timeout for telemetry workers is strictly `45 seconds` with heartbeat renewals every `12 seconds`.
3. Every archived payload is hashed with `BLAKE3` before transfer to cold object storage bucket `horizon-vault-09`.

## Suggested Live Demo Prompts
- *"According to the uploaded Project Horizon runbook, what port does the Quantum Orchid Telemetry Gateway listen on and what cooling module does it use?"*
- *"What is the exact escalation code and worker lease timeout specified in Project Horizon?"*
- *"Which regional failover node handles latency spikes above 240 ms?"*
