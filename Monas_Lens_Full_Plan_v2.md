# Monas Lens — Full Product, Technical & Commercial Plan

## 1. Product Vision

**Monas Lens** is a local-first repository intelligence and safety layer for AI coding agents.

It does not replace Claude Code, Codex, Cursor, Cline, Roo Code, Copilot, or local coding agents.

It helps those agents:

- Find the correct repository context in one tool call.
- Avoid repeated `grep`, `find`, and `read_file` loops.
- Reduce unnecessary context tokens.
- Understand callers, dependencies, tests, configuration, and recent changes.
- Detect patch impact and potential regressions.
- Preserve repository privacy by running locally.

Core promise:

> **One task. One context call.**

Long-term positioning:

> **Monas Lens is the repository intelligence and safety layer for AI coding.**

Tagline:

> **Less context. Better code.**

---

## 2. Product Direction

### Stage 1 — Repository Context Engine

```text
Task
→ Find correct files and symbols
→ Return focused context
→ Reduce tool calls and tokens
```

### Stage 2 — Repository Brain

Monas Lens begins to retain:

```text
Architecture
Project conventions
Historical fixes
Known risky areas
Testing patterns
Past regressions
Technical decisions
```

### Stage 3 — AI Code Safety Layer

Monas Lens validates:

```text
Did the agent read enough context?
Did the patch affect other modules?
Are tests missing?
Does the patch violate architecture?
Does it repeat a known failure?
Did the agent modify unrelated files?
```

---

## 3. Active Product Editions

For the current business stage, Monas Lens has two active editions:

```text
Community
Pro
```

Team and Enterprise are postponed because:

- No dedicated VPS is available.
- No capital is allocated for team infrastructure.
- Product demand must be proven first.
- Local-first Community and Pro are sufficient for launch.

---

## 4. Monas Lens Community

### 4.1 Purpose

Community is the public open-source edition.

Goals:

```text
Adoption
GitHub stars
Community trust
Benchmark data
User feedback
Language contributions
Real-world validation
```

Community must remain genuinely useful. Retrieval quality must not be intentionally weakened to force upgrades.

### 4.2 Features

```text
Local MCP server
Repository scanner
Tree-sitter parsing
Symbol extraction
SQLite metadata
SQLite FTS5 search
Local Qdrant support
Basic graph index
One-context-call retrieval
Basic token savings report
Basic patch impact analysis
Claude Code integration
Codex integration
One active repository
```

### 4.3 License

Recommended:

```text
Apache-2.0
```

Public repository:

```text
github.com/monas-lens/monas-lens
```

---

## 5. Monas Lens Pro

### 5.1 Purpose

Pro is a closed-source local product for developers who use AI coding tools frequently.

Pro sells measurable improvement rather than basic indexing:

```text
Higher retrieval accuracy
Better repository memory
Fewer regressions
Better large-repository performance
Cross-repository intelligence
More measurable token savings
```

### 5.2 Features

```text
Adaptive ranking per repository
Persistent technical memory
Advanced impact analysis
Advanced regression guard
Cross-repository context
Automatic AGENTS.md generation
Context quality scoring
Historical task comparison
Repository-specific learning
Advanced token analytics
Large repository optimization
Private local dashboard
```

Core promise:

> **Monas Lens learns how your repository works and becomes more accurate over time.**

### 5.3 Pricing

Suggested initial pricing:

```text
Early Access:
- US$5/month
- US$49/year

Optional early lifetime license:
- US$59–79

Official Pro after validation:
- US$9–12/month
```

---

## 6. Commercial Validation Gates

Do not launch Pro publicly until:

```text
100+ active Community users
20+ weekly active repositories
10+ benchmark case studies
Median token reduction >= 60%
No lower task success rate than raw agent search
10+ users explicitly requesting advanced features
5+ users willing to pay
```

Users are unlikely to pay for:

```text
Dashboard only
Graph visualization only
Basic indexing
Basic MCP support
Theme or UI upgrades
```

Users are more likely to pay for:

```text
Lower AI usage cost
Better coding accuracy
Technical memory
Regression prevention
Large repository support
Cross-repository understanding
```

---

## 7. Open Source and Pro Protection

### 7.1 Repository Separation

```text
monas-lens-community
→ public
→ Apache-2.0

monas-lens-pro
→ private
→ closed source

monas-license-server
→ private
→ closed source
```

Do not include Pro logic in the public repository behind a feature flag.

### 7.2 Public Components

```text
CLI
MCP adapter
Schemas
Basic indexer
Basic ranker
Basic impact analyzer
Language plugins
```

### 7.3 Private Components

```text
Adaptive ranker
Technical memory
Advanced regression engine
Cross-repository engine
Advanced analytics
Pro dashboard
License client
```

### 7.4 Pro Distribution

Recommended architecture:

```text
Open-source Python MCP shell
        ↓ local IPC
Closed-source Monas Pro Engine binary
        ↓
Local repository
```

Preferred Pro engine language:

```text
Rust or Go
```

Fallback:

```text
Python packaged with Nuitka
```

The goal is deterrence, not impossible-to-break protection.

---

## 8. Deployment Modes

### 8.1 Local MCP

Default for Community and Pro:

```text
Claude Code / Codex
        ↓
launch subprocess
        ↓
monas-lens mcp
        ↓
local repository index
```

Users should not need to clone source, start FastAPI manually, expose local ports, or run Docker.

Installation:

```bash
pipx install monas-lens
monas-lens init
```

Example MCP configuration:

```json
{
  "mcpServers": {
    "monas-lens": {
      "command": "monas-lens",
      "args": ["mcp"]
    }
  }
}
```

### 8.2 License and Payment Server

Existing infrastructure:

```text
Domain: monas.io.vn
Cloudflare Tunnel
Local service port: 8002
SePay QR payment logic
SePay webhook logic
```

Public route:

```text
https://monas.io.vn
        ↓ Cloudflare Tunnel
http://localhost:8002
```

The server handles only:

```text
Orders
Payments
Licenses
Activations
Renewals
Revocations
Pro downloads
Update metadata
```

It must not process user repositories.

---

## 9. Payment Architecture

### 9.1 Flow

```text
User selects Pro plan
        ↓
Server creates order
        ↓
Server generates SePay QR
        ↓
User transfers payment
        ↓
SePay webhook confirms payment
        ↓
Server validates transaction
        ↓
License is created
        ↓
User activates Monas Lens Pro
```

### 9.2 Create Order

```http
POST /api/orders
```

Request:

```json
{
  "email": "user@example.com",
  "plan": "pro_yearly"
}
```

Response:

```json
{
  "order_id": "MONAS-20260723-ABC123",
  "amount": 1290000,
  "currency": "VND",
  "qr_url": "...",
  "payment_content": "MONAS ABC123",
  "expires_at": "2026-07-23T17:00:00+07:00"
}
```

### 9.3 SePay Webhook

```http
POST /api/webhooks/sepay
```

Processing must:

```text
Verify SePay authentication
Validate transaction ID
Validate amount
Validate transfer content
Prevent duplicate processing
Store raw webhook payload
Mark order paid
Generate license
Record audit event
```

### 9.4 Order States

```text
pending
paid
expired
cancelled
refunded
manual_review
```

---

## 10. License Architecture

### 10.1 Activation

```bash
monas-lens activate MONAS-XXXX-XXXX-XXXX
```

Endpoint:

```http
POST /api/licenses/activate
```

Request:

```json
{
  "license_key": "MONAS-XXXX-XXXX-XXXX",
  "device_id": "hashed-device-id",
  "app_version": "1.0.0"
}
```

Response:

```json
{
  "status": "active",
  "plan": "pro",
  "expires_at": "2027-07-23T00:00:00Z",
  "features": [
    "adaptive_ranking",
    "technical_memory",
    "advanced_impact"
  ],
  "license_token": "signed-token"
}
```

### 10.2 Signed License Token

Use asymmetric signing:

```text
Ed25519
```

Architecture:

```text
Server stores private key
Client stores public key
```

Signed payload:

```text
License ID
Plan
User ID
Device ID
Expiration
Feature list
Issued time
Grace period
```

Do not use unsigned JSON, reversible flags, or `PRO_ENABLED = True`.

### 10.3 Offline Operation

```yaml
online_check_interval: 7 days
offline_grace_period: 30 days
```

The client must not call the server for every coding task.

### 10.4 License States

```text
active
expired
revoked
suspended
```

### 10.5 Device Policy

```text
Maximum 2 devices per license
Manual device reset allowed
No aggressive hardware fingerprint lock
```

---

## 11. License Server Structure

```text
monas_license_server/
├── main.py
├── config.py
├── api/
│   ├── orders.py
│   ├── licenses.py
│   ├── activations.py
│   ├── downloads.py
│   └── health.py
├── webhooks/
│   └── sepay.py
├── services/
│   ├── qr_service.py
│   ├── payment_service.py
│   ├── license_service.py
│   ├── signing_service.py
│   ├── activation_service.py
│   └── email_service.py
├── models/
│   ├── user.py
│   ├── order.py
│   ├── transaction.py
│   ├── license.py
│   ├── activation.py
│   └── webhook_event.py
├── db/
│   ├── session.py
│   └── migrations/
└── tests/
```

---

## 12. License Server Database

Minimum tables:

```text
users
orders
payment_transactions
licenses
license_activations
webhook_events
audit_logs
```

Important unique constraint:

```sql
CREATE UNIQUE INDEX ux_payment_transaction
ON payment_transactions(provider, provider_transaction_id);
```

Also enforce uniqueness on:

```text
orders.order_id
licenses.license_key_hash
license_activations.license_id + device_id
webhook_events.provider + event_id
```

Never store license keys in plaintext.

---

## 13. Webhook Security

Required:

```text
HTTPS through Cloudflare
SePay token or signature validation
Strict request validation
Idempotency
Amount verification
Payment content verification
Provider transaction uniqueness
Webhook audit logging
Rate limiting
Replay protection
```

Never trust client-side payment status, client-provided amount, client-provided plan, or unverified webhook data.

If transaction data does not match:

```text
Move order to manual_review
Do not generate a license
```

---

## 14. Privacy Model

Marketing promise:

> **Your code stays local.**

License server stores only:

```text
Email
Order
Payment transaction
License
Device activation
App version
Basic audit logs
```

It must not store:

```text
Repository source code
Repository index
Prompts
Context bundles
Git diffs
Agent conversations
Test output
```

Optional telemetry must be opt-in.

---

## 15. Core Technology Stack

```yaml
local_core:
  runtime: Python 3.12
  api: FastAPI
  validation: Pydantic v2
  parser: Tree-sitter
  metadata: SQLite
  keyword_search: SQLite FTS5
  vector_store: Qdrant Local Mode
  embeddings: Ollama
  embedding_model: embeddinggemma
  file_watch: watchfiles
  git: Git CLI
  transport: MCP stdio
  tests: pytest
  lint: Ruff
  type_check: Pyright

license_server:
  framework: FastAPI
  port: 8002
  domain: monas.io.vn
  tunnel: Cloudflare Tunnel
  payment: SePay
  signing: Ed25519
```

Do not introduce in MVP:

```text
Neo4j
Redis
Celery
Kubernetes
LangChain
Team cloud architecture
Complex multi-agent orchestration
```

---

## 16. Core Local Architecture

```text
Repository
    ↓
Repository Scanner
    ↓
Ignore Filter
    ↓
Language Detector
    ↓
Tree-sitter Parser
    ↓
Symbol and Chunk Extractor
    ↓
Graph Builder
    ↓
Index Storage
    ├── SQLite metadata
    ├── SQLite FTS5
    └── Qdrant vectors
            ↓
Task Resolver
            ↓
Parallel Retriever
            ↓
Ranker
            ↓
Confidence Gate
            ↓
Context Bundle
            ↓
MCP
```

---

## 17. Local Source Structure

```text
monas_lens/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── lifespan.py
│   ├── api/
│   ├── mcp/
│   ├── indexing/
│   ├── retrieval/
│   ├── impact/
│   ├── analytics/
│   ├── licensing/
│   ├── db/
│   ├── schemas/
│   └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── storage/
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 18. Indexing Design

### 18.1 Scanner

```text
Respect .gitignore
Exclude dependencies
Exclude generated files
Exclude binary assets
Exclude build directories
Detect supported languages
Hash each file
Skip unchanged files
```

Initial languages:

```text
Python
JavaScript
TypeScript
Dart
```

### 18.2 Tree-sitter Extraction

```text
Modules
Classes
Functions
Methods
Imports
Exports
Parameters
Return types
Docstrings
Call expressions
Constants
Routes
Test functions
```

### 18.3 Syntax-Aware Chunks

```text
Function
Method
Small class
Module summary
Configuration section
Test case
```

### 18.4 Graph Relations

```text
imports
calls
references
inherits
implements
tested_by
configured_by
changed_with
```

### 18.5 Search Indexes

SQLite FTS5:

```text
Symbols
Paths
Signatures
Configuration keys
Error messages
Code text
```

Qdrant:

```text
Functions
Classes
Module summaries
Tests
Documentation
```

### 18.6 Incremental Indexing

```text
1. Calculate file hash.
2. Skip unchanged files.
3. Remove old symbols, chunks, vectors, and edges.
4. Parse changed files.
5. Insert updated records.
6. Rebuild directly affected graph relations.
7. Re-embed changed chunks only.
```

---

## 19. Main MCP Tools

### resolve_task_context

Mandatory first call.

### expand_context

Optional, maximum one call, and must return only new information.

### analyze_patch_impact

Returns changed symbols, affected callers, routes, schemas, tests, breaking risks, missing validations, and unrelated changes.

### compress_command_output

Supports test, build, compiler, linter, stack trace, and Git diff output.

---

## 20. Retrieval Pipeline

Priority:

```text
1. Exact symbol detection
2. File and path detection
3. Error message lookup
4. FTS keyword search
5. Graph expansion
6. Semantic search fallback
```

Parallel retrieval:

```text
Exact symbol search ─────────┐
FTS keyword search ──────────┤
Semantic search ─────────────┤
Graph traversal ─────────────┼── Ranker
Test relationship search ────┤
Configuration search ────────┤
Git history search ──────────┘
```

Ranking:

```yaml
exact_symbol_match: 0.35
graph_relationship: 0.25
lexical_match: 0.20
test_relationship: 0.10
semantic_similarity: 0.10
```

---

## 21. Context Bundle Rules

Include:

```text
Primary definition
Direct callers
Direct dependencies
Interface or base type
Relevant schema
Relevant configuration
Two or three related tests
Current Git diff
Suggested validation commands
```

Defaults:

```yaml
max_primary_targets: 3
max_dependency_snippets: 6
max_caller_snippets: 6
max_test_snippets: 4
max_git_entries: 5
max_total_context_tokens: 12000
```

Return focused line ranges and deduplicate by content hash.

---

## 22. Confidence Gate

```text
Confidence >= 0.80
→ return bundle

Confidence < 0.80
→ widen graph and retrieval scope internally
→ rerank
→ return improved bundle
```

---

## 23. Performance Requirements

```yaml
symbol_lookup_target_ms: 20
graph_traversal_target_ms: 30
vector_search_target_ms: 100
ranking_target_ms: 80
total_context_resolution_target_ms: 500
```

Index states:

```text
pending
scanning
parsing
embedding
building_graph
ready
failed
```

---

## 24. Coding Agent Rules

```text
1. Always call resolve_task_context first.
2. Do not use raw grep, find, or read tools before receiving the bundle.
3. Use returned snippets, relations, tests, and validation commands.
4. Call expand_context only for one clearly identified missing relationship.
5. expand_context may be called at most once.
6. Do not request duplicated context.
7. After creating a patch, call analyze_patch_impact.
8. Run recommended validation commands.
9. Do not claim completion while validation fails.
```

Configuration:

```yaml
agent:
  max_discovery_calls: 2
  max_context_expansions: 1
  allow_raw_repository_search: false
  require_patch_impact_analysis: true
```

---

## 25. Analytics

Community:

```text
Estimated raw context tokens
Monas Lens context tokens
Tokens saved
Files avoided
Repeated reads prevented
Retrieval latency
```

Pro:

```text
Historical comparison
Monthly token savings
Context quality score
Repository-specific improvements
Regression prevention history
```

---

#
# 25. Retrieval Models: Embedding, Reranking and Ollama

This section is mandatory. Do not leave model selection implicit.

## 25.1 Retrieval Model Strategy

Monas Lens uses a multi-stage retrieval pipeline:

```text
Task query
    ↓
Exact symbol / path / error lookup
    ↓
SQLite FTS5 lexical retrieval
    ↓
Graph expansion
    ↓
Dense embedding retrieval
    ↓
Candidate fusion and deduplication
    ↓
Reranker
    ↓
Context Bundle Builder
```

Important principles:

```text
Exact code relationships outrank semantic similarity.
Embedding expands recall.
Reranking improves precision.
The reranker must not process the entire repository.
```

The default retrieval path should work without a reranker when exact symbol,
FTS and graph confidence are already high.

## 25.2 Default Embedding Model

Default model:

```yaml
embedding:
  provider: ollama
  model: qwen3-embedding:0.6b
  endpoint: http://127.0.0.1:11434/api/embed
  distance: cosine
  normalize_vectors: true
  batch_size: 32
  keep_alive: 10m
```

Reasons for choosing `qwen3-embedding:0.6b`:

```text
Small enough for normal developer machines
Multilingual
Suitable for Vietnamese and English task descriptions
Long-context support
Available directly through Ollama
Lower latency than 4B and 8B embedding variants
Good default balance between quality and local resource usage
```

Installation:

```bash
ollama pull qwen3-embedding:0.6b
```

Example embedding request:

```bash
curl http://127.0.0.1:11434/api/embed \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-embedding:0.6b",
    "input": [
      "query: Fix refresh token expiration",
      "document: AuthService validates refresh token expiration and rotation"
    ],
    "truncate": false,
    "keep_alive": "10m"
  }'
```

Python client:

```python
from __future__ import annotations

import httpx


async def embed_texts(
    texts: list[str],
    *,
    model: str = "qwen3-embedding:0.6b",
    base_url: str = "http://127.0.0.1:11434",
) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/api/embed",
            json={
                "model": model,
                "input": texts,
                "truncate": False,
                "keep_alive": "10m",
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["embeddings"]
```

## 25.3 Embedding Model Profiles

Monas Lens should support explicit hardware profiles.

### Lightweight profile

```yaml
profile: lightweight
embedding_model: qwen3-embedding:0.6b
reranker_enabled: false
semantic_top_k: 20
final_top_k: 8
```

Recommended for:

```text
CPU-only machines
8 GB system RAM
Low-power laptops
Repositories under approximately 100,000 lines
```

### Balanced profile

```yaml
profile: balanced
embedding_model: qwen3-embedding:0.6b
reranker_model: Qwen/Qwen3-Reranker-0.6B
semantic_top_k: 30
rerank_top_n: 20
final_top_k: 8
```

This is the recommended default.

### Quality profile

```yaml
profile: quality
embedding_model: qwen3-embedding:4b
reranker_model: Qwen/Qwen3-Reranker-4B
semantic_top_k: 50
rerank_top_n: 30
final_top_k: 10
```

Recommended only when sufficient RAM or VRAM is available.

Installation:

```bash
ollama pull qwen3-embedding:4b
```

### Compatibility profile

Alternative embedding model:

```yaml
embedding_model: bge-m3
```

Install:

```bash
ollama pull bge-m3
```

Use `bge-m3` when:

```text
A smaller established multilingual embedding stack is preferred
Compatibility testing shows better repository-specific results
The deployment already uses BGE-based retrieval
```

Do not mix vectors from different embedding models in one collection.

Changing embedding model requires:

```text
Create a new collection
Re-embed all chunks
Switch collection only after indexing completes
```

## 25.4 Embedding Text Format

Do not embed raw code without metadata.

Query format:

```text
query: {user task}
intent: {bug_fix | refactor | feature | test | explanation}
symbols: {detected symbols}
paths: {detected paths}
errors: {detected error messages}
```

Code chunk format:

```text
document_type: function
language: python
path: app/services/auth.py
symbol: AuthService.rotate_refresh_token
signature: rotate_refresh_token(token: str) -> TokenPair
imports: TokenRepository, TokenService
summary: Rotates and invalidates refresh tokens.
code:
{source code}
```

Test chunk format:

```text
document_type: test
language: python
path: tests/services/test_auth.py
symbol: test_refresh_token_rotation
tests_symbol: AuthService.rotate_refresh_token
code:
{test source}
```

Store separately:

```text
embedding_text
raw_source
metadata
content_hash
embedding_model
embedding_dimension
```

## 25.5 Embedding Index Rules

Only embed:

```text
Functions
Methods
Small classes
Module summaries
Tests
Documentation sections
Configuration sections with meaningful text
```

Do not embed:

```text
Binary files
Generated files
Minified files
Lock files
Entire large modules as one vector
Every line independently
Duplicate chunks
```

Recommended indexing policy:

```yaml
minimum_chunk_characters: 80
maximum_chunk_tokens: 1200
overlap_tokens: 0
deduplicate_by_content_hash: true
```

Syntax boundaries replace text overlap.

## 25.6 Query Embedding Cache

Cache normalized task embeddings.

Cache key:

```text
sha256(
  embedding_model
  + normalized_query
  + detected_intent
  + detected_symbols
)
```

Recommended:

```yaml
query_embedding_cache:
  enabled: true
  max_entries: 1000
  ttl: 7d
```

Do not regenerate the same query embedding repeatedly during one agent task.

## 25.7 Reranker Model

Recommended default reranker:

```yaml
reranker:
  runtime: sentence-transformers
  model: Qwen/Qwen3-Reranker-0.6B
  device: auto
  batch_size: 8
  max_length: 4096
  rerank_top_n: 20
  final_top_k: 8
```

Higher quality option:

```yaml
model: Qwen/Qwen3-Reranker-4B
```

Do not use the 8B reranker as the default because it adds unnecessary latency
and memory pressure for a local developer tool.

The reranker receives pairs:

```text
(query, candidate document)
```

It returns one relevance score for each candidate.

The reranker should process only the top candidates collected by:

```text
Exact search
FTS5
Graph retrieval
Dense vector retrieval
```

Recommended flow:

```text
Retrieve 30 candidates
→ deduplicate to approximately 20
→ rerank 20
→ return top 8
```

## 25.8 Why Reranking Is Not Performed Through `/api/embed`

An embedding model and a reranker are different:

```text
Embedding:
text → reusable vector

Reranker:
query + document → direct relevance score
```

Never call `/api/embed` with a reranker model and treat the returned output as
a reranking score.

## 25.9 Ollama Rerank Limitation

At the time this plan was updated, Ollama provides a first-class embedding
endpoint:

```text
POST /api/embed
```

However, it does not provide a stable first-class endpoint such as:

```text
POST /api/rerank
```

Therefore the production default must be:

```text
Ollama for embedding
Sentence Transformers or Transformers for reranking
```

Recommended architecture:

```text
Ollama
└── qwen3-embedding:0.6b

Monas Lens local process
└── Qwen3-Reranker-0.6B through Sentence Transformers
```

This remains fully local and does not require a cloud API.

## 25.10 Optional Ollama-Compatible Generative Rerank

An experimental compatibility mode may run a reranker-like model through
Ollama's generation endpoint.

This mode is not the default.

Configuration:

```yaml
reranker:
  runtime: ollama_generate
  model: dengcao/Qwen3-Reranker-0.6B
  endpoint: http://127.0.0.1:11434/api/generate
  enabled: false
  experimental: true
```

Conceptual request:

```bash
curl http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dengcao/Qwen3-Reranker-0.6B",
    "prompt": "Determine whether the document answers the query. Return JSON only.\nQuery: Fix refresh token expiration\nDocument: AuthService rotates refresh tokens and validates expiry.",
    "stream": false,
    "format": {
      "type": "object",
      "properties": {
        "relevant": {"type": "boolean"},
        "score": {"type": "number"}
      },
      "required": ["relevant", "score"]
    },
    "options": {
      "temperature": 0
    }
  }'
```

Limitations:

```text
The generated numeric score may not be calibrated
It is slower than a dedicated cross-encoder runtime
Community model templates may vary
Results can differ between quantizations
It lacks a stable native rerank contract
```

Because of these limitations, this mode is only:

```text
Fallback
Compatibility experiment
User-selected option
```

It must not be used for benchmark claims unless separately measured.

## 25.11 Reranker Service Interface

Use a runtime-independent interface:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RerankItem:
    candidate_id: str
    text: str


@dataclass(frozen=True)
class RerankResult:
    candidate_id: str
    score: float


class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        items: list[RerankItem],
        *,
        top_k: int,
    ) -> list[RerankResult]:
        ...
```

Implementations:

```text
NoOpReranker
SentenceTransformersReranker
TransformersReranker
OllamaGenerateReranker
```

The retrieval pipeline must not depend directly on one runtime.

## 25.12 Reranking Bypass Rules

Skip model reranking when deterministic confidence is already high.

Examples:

```text
Exact fully qualified symbol match
Exact file path and symbol match
Compiler error contains a unique path and line
Graph identifies one direct definition and its tests
```

Suggested rule:

```yaml
rerank:
  bypass_when:
    exact_symbol_score_gte: 0.98
    deterministic_confidence_gte: 0.90
    candidates_lte: 5
```

This reduces latency.

## 25.13 Candidate Fusion

Use reciprocal rank fusion or a normalized weighted fusion before reranking.

Suggested weights:

```yaml
candidate_fusion:
  exact_symbol: 0.35
  graph: 0.25
  lexical_fts: 0.20
  dense_embedding: 0.10
  test_relation: 0.05
  git_relation: 0.05
```

After reranking, combine scores:

```yaml
final_score:
  deterministic_retrieval: 0.55
  reranker: 0.45
```

Do not allow a semantic reranker to completely override exact code facts.

## 25.14 Latency Budget

Balanced profile target:

```yaml
task_parse_ms: 10
fts_and_symbol_ms: 20
graph_ms: 30
query_embedding_ms_warm: 100
vector_search_ms: 50
candidate_fusion_ms: 10
rerank_20_candidates_ms: 250
context_assembly_ms: 50
total_target_ms: 500
```

If the reranker cannot meet the budget:

```text
Reduce rerank_top_n
Use the 0.6B model
Use CPU quantization or ONNX
Skip reranking for exact tasks
Return deterministic results first
```

## 25.15 Model Loading Policy

Avoid loading and unloading models for every task.

```yaml
models:
  embedding_keep_alive: 10m
  reranker_idle_unload: 15m
  preload_on_repository_open: false
  lazy_load: true
```

For the first query:

```text
Run exact, FTS and graph retrieval immediately
Load the reranker only when needed
```

## 25.16 Failure and Fallback Policy

If Ollama is unavailable:

```text
Exact symbol + FTS5 + graph retrieval continues
Semantic search is marked unavailable
No repository operation should fail completely
```

If the reranker is unavailable:

```text
Use fused retrieval scores
Return context with reranker_used=false
Lower confidence when necessary
```

Response metadata:

```json
{
  "embedding": {
    "provider": "ollama",
    "model": "qwen3-embedding:0.6b",
    "used": true
  },
  "reranker": {
    "runtime": "sentence-transformers",
    "model": "Qwen/Qwen3-Reranker-0.6B",
    "used": true,
    "bypassed": false
  }
}
```

## 25.17 Configuration Example

```yaml
retrieval:
  profile: balanced

  embedding:
    enabled: true
    provider: ollama
    base_url: http://127.0.0.1:11434
    model: qwen3-embedding:0.6b
    distance: cosine
    normalize: true
    batch_size: 32
    keep_alive: 10m
    truncate: false

  vector_store:
    provider: qdrant_local
    collection_prefix: monas_lens
    top_k: 30

  reranker:
    enabled: true
    runtime: sentence_transformers
    model: Qwen/Qwen3-Reranker-0.6B
    device: auto
    batch_size: 8
    max_length: 4096
    rerank_top_n: 20
    final_top_k: 8
    deterministic_bypass_confidence: 0.90

  fallback:
    allow_lexical_only: true
    allow_graph_only: true
    fail_open: true
```

## 25.18 Model Installation Command

Provide a setup command:

```bash
monas-lens models install --profile balanced
```

Equivalent actions:

```bash
ollama pull qwen3-embedding:0.6b
```

And install the reranker runtime:

```bash
pip install "sentence-transformers>=5"
```

The CLI should validate:

```text
Ollama is reachable
Embedding model exists
Reranker dependencies exist
Model can process a test query
Vector dimensions match the collection
```

## 25.19 Model Benchmark Requirements

Do not select models only from public leaderboard claims.

Benchmark against Monas Lens coding tasks:

```text
Exact symbol lookup
Natural-language bug description
Error message to source
Cross-file call relationship
Configuration-related bug
Test discovery
Vietnamese task → English code
English task → mixed-language repository
```

Compare:

```text
qwen3-embedding:0.6b
qwen3-embedding:4b
bge-m3
```

Rerank comparison:

```text
No reranker
Qwen3-Reranker-0.6B
Qwen3-Reranker-4B
Experimental Ollama generative rerank
```

Metrics:

```text
Recall@20
MRR
nDCG@10
Top-1 target accuracy
Context precision
Task success rate
Retrieval latency
Peak RAM
Peak VRAM
```

Default model may change only after benchmark evidence.

## 25.20 Final Model Decision

Initial production defaults:

```yaml
embedding:
  model: qwen3-embedding:0.6b
  runtime: ollama

reranker:
  model: Qwen/Qwen3-Reranker-0.6B
  runtime: sentence-transformers

fallback_embedding:
  model: bge-m3
  runtime: ollama

experimental_reranker:
  runtime: ollama_generate
  enabled: false
```

This gives Monas Lens:

```text
Fast local embedding
Multilingual retrieval
Dedicated high-precision reranking
No cloud dependency
Graceful operation when models are unavailable
```


# 27. Release Roadmap

### Phase 1 — Foundation

```text
FastAPI foundation
CLI
Configuration
SQLite
Repository registration
Health checks
```

### Phase 2 — Structural Index

```text
Repository scanner
.gitignore support
Tree-sitter parser
Symbol extraction
Syntax-aware chunks
File hashing
Incremental indexing
```

### Phase 3 — Search and Graph

```text
SQLite FTS5
Import graph
Basic call graph
Test-source links
Configuration links
```

### Phase 4 — Context Compiler

```text
Task Resolver
Parallel Retriever
Ranker
Confidence Gate
Context Bundle
Token estimator
```

### Phase 5 — Community MCP Release

```text
MCP stdio
resolve_task_context
expand_context
analyze_patch_impact
compress_command_output
Claude Code integration
Codex integration
```

Public release targets:

```text
One task, one context call
At least 60% fewer context tokens
At most two discovery calls
Under 500 ms retrieval after indexing
```

### Phase 6 — Community Validation

```text
Documentation
Demo video
Benchmark repository
GitHub stars
Bug reports
Case studies
Language contributions
```

### Phase 7 — Pro Engine

```text
Adaptive ranking
Technical memory
Advanced impact guard
Advanced regression detection
Cross-repository context
Local dashboard
Advanced analytics
```

### Phase 8 — License and Payment Server

Use:

```text
monas.io.vn
Cloudflare Tunnel
Port 8002
SePay QR
SePay webhook
```

Build:

```text
Order API
Payment validation
License generation
License activation
Signed entitlement
Renewal
Revocation
Download authorization
```

### Phase 9 — Pro Early Access

Offer monthly, yearly, and optional lifetime early-adopter plans.

Measure:

```text
Paid conversion
Retention
Support burden
Feature usage
License issues
Retrieval quality
```

### Phase 10 — Future Review

Only reconsider Team when:

```text
Community adoption is stable
Pro generates recurring revenue
Users request shared indexes
A VPS budget exists
Operational capacity exists
```

---

## 28. Required Tests

### Local Core

```text
Ignore filtering
Language detection
Tree-sitter extraction
Symbol IDs
Chunk boundaries
File hashing
FTS ranking
Graph traversal
Hybrid ranking
Context deduplication
Token budgeting
Confidence calculation
Token savings estimation
License token verification
```

### License Server

```text
Create order
Generate SePay QR
Valid webhook
Duplicate webhook
Wrong amount
Wrong transfer content
Expired order
License generation
License activation
Second device activation
Revoked license
Offline token verification
```

### Benchmarks

```text
Missing import
Wrong configuration key
Broken API schema
Expired session logic
Cross-file rename
Missing regression test
Unrelated patch change
```

---

## 29. Security Requirements

Local client:

```text
No path traversal
No shell injection
No unsafe Git command construction
No plaintext license storage
No secret leakage in logs
No repository upload
```

License server:

```text
Webhook authentication
Idempotency
Rate limiting
Signed licenses
Private key protection
Audit logs
Strict request validation
Unique transaction constraints
Cloudflare HTTPS only
```

Do not expose port 8002 directly to the internet.

---

## 30. Mandatory Quality Checks

```text
ruff format .
ruff check .
pyright
pytest
```

Also verify:

```text
No missing imports
No undefined variables
No invalid attributes
No circular imports
No mutable defaults
No path traversal
No unrelated changes
No placeholder implementation
No duplicate payment handling
No unsigned licenses
```

---

## 31. First Coding Task

Start only with Phase 1 and Phase 2.

```text
1. Inspect the repository.
2. List existing files and dependencies.
3. Reuse existing components.
4. Produce a short implementation plan.
5. Implement the foundation.
6. Implement repository scanning.
7. Implement Tree-sitter indexing.
8. Add tests.
9. Run all quality checks.
10. Report changed files, tests, results, and limitations.
```

Do not implement Qdrant, Pro engine, licensing, billing, SePay, or Team features until the structural index is stable.

---

## 32. Final Product Strategy

```text
Community
- Open source
- Local MCP
- Free
- Public GitHub repository

Pro
- Closed-source local engine
- Local-first
- Paid through SePay
- License server at monas.io.vn
- Cloudflare Tunnel to port 8002
```

No Team product yet.

Strongest product message:

> **Your code stays local. Your agent gets the right context in one call.**

Strongest commercial message:

> **Monas Lens helps coding agents use less context, make fewer mistakes, and avoid regressions.**
