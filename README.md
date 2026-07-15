# Hubster

![Tests](https://github.com/alexmonteirocastro/hubster/actions/workflows/test.yml/badge.svg) ![Deploy](https://github.com/alexmonteirocastro/hubster/actions/workflows/deploy.yml/badge.svg)

Hubster ingests job listings from [The Hub](https://thehub.io/) via their public API, embeds the content via **Qdrant Cloud Inference** (`intfloat/multilingual-e5-small`), and stores the results in [Qdrant](https://qdrant.tech/) for semantic search — with a `/chat` RAG layer and React UI for natural-language job discovery across Nordic/European startup markets.

## Live deployment

- **App:** https://hubster-2ox.pages.dev
- **API:** https://hubster-alpi.onrender.com
- Hosted on Cloudflare Pages (frontend) + Render (backend) + Qdrant Cloud (vector store), all free-tier. See [ADR-0013](docs/adr/0013-deployment-strategy.md) for the full rationale and accepted trade-offs.

## Quick start (Docker)

### 1. Configure environment

```bash
cd hubster
cp .env.example .env
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#environment-variables) for the full variable reference. **Embedding requires Qdrant Cloud** — set `QDRANT_URL`, `QDRANT_API_KEY`, and `EMBEDDING_MODEL=intfloat/multilingual-e5-small` in `.env` (see [ADR-0014](docs/adr/0014-embedding-model-migration.md)).

### 2. Start the stack

```bash
docker compose up --build
```

This starts:

- **api** — FastAPI backend on [localhost:8000](http://localhost:8000) ([Swagger UI](http://localhost:8000/docs))
- **frontend** — React chat UI on [localhost:5173](http://localhost:5173)

### 3. Run ingestion

Ingestion is gated behind a Compose profile so it never runs accidentally on `docker compose up`:

```bash
# Full bootstrap seed (first run only)
docker compose --profile ingestion run --rm ingestion python main.py --seed

# Incremental sync (subsequent runs) — add new jobs, remove delisted ones
docker compose --profile ingestion run --rm ingestion
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#ingestion) for sync vs seed details, backfill, scheduling, and known limitations.

## REST API

The FastAPI service exposes a stable JSON contract for any frontend or client. It wraps existing Hubster logic — it does not reimplement ingestion or retrieval.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Process liveness probe (`{"status": "ok"}`); no dependency checks |
| `GET /jobs/stats?country={code}` | Job totals and role breakdown for a country (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`) |
| `GET /jobs/search?q={query}&limit={n}&country={code}&remote={true|false}` | Semantic search over the Qdrant collection (default `limit=5`, max `50`). Optional `country` filter (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`) and optional `remote` filter constrain results via Qdrant payload filtering. |
| `POST /chat` | Single-turn RAG chat: retrieve jobs from Qdrant, then generate a grounded answer via the `Generator` interface (Gemini 2.5 Flash by default; optional local Ollama or instant stub — see [ADR-0007](docs/adr/0007-local-generation-fallback-ollama-qwen3.md) and [CONTRIBUTING.md](CONTRIBUTING.md#local-generation-for-development)). **Request:** `question` (required, max **500** characters — bounds token cost and latency before any retrieval or generation), optional `limit` (default 5), optional `country` (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`), optional `remote` (`true` = remote only, `false` = on-site only). When `country`/`remote` are omitted, `/chat` infers them from the question text via deterministic keyword matching; explicit request fields always override inferred values. **Rate limit:** per-client in-memory limit on `/chat` only (default **10 requests/minute**; returns 429 when exceeded). `/jobs/search` and `/jobs/stats` are not rate-limited. Override via `CHAT_QUESTION_MAX_LENGTH`, `CHAT_RATE_LIMIT`, and `CHAT_SOURCE_MIN_SCORE` (default **0.85**) in `.env`. **Response:** `question`, `answer`, `sources` (retrieved job hits with scores **at or above** `CHAT_SOURCE_MIN_SCORE` — weaker matches are omitted, so fewer than `limit` sources may be returned), `generated` (`true` when the LLM produced the answer), `applied_country` / `applied_remote` (the filters actually used for retrieval — `null` when nothing was resolved). See [ADR-0001](docs/adr/0001-llm-provider-strategy.md), [ADR-0002](docs/adr/0002-retrieval-filtering-strategy.md), [ADR-0006](docs/adr/0006-chat-endpoint-hardening.md), [ADR-0007](docs/adr/0007-local-generation-fallback-ollama-qwen3.md), [ADR-0009](docs/adr/0009-grounded-inline-job-hyperlinks.md), and [ADR-0014](docs/adr/0014-embedding-model-migration.md). |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs) when the `api` service is running.

## Dev workflow

See [CONTRIBUTING.md](CONTRIBUTING.md#code-quality) for Ruff, mypy, oxlint, pre-commit setup, and the CI checks to run locally before opening a PR.

## Known limitations

- **Cold start on first request:** the backend runs on Render's free tier, which spins down after 15 minutes of inactivity. The first `/chat` or `/jobs/*` request after a quiet period may take 30–60s to respond while the service wakes up. This is a known, accepted trade-off of the free-tier hosting (see [ADR-0013](docs/adr/0013-deployment-strategy.md)) — not fixed for the prototype stage.

## Where to go next

- [CONTRIBUTING.md](CONTRIBUTING.md) — code-quality tooling and dev checks
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — environment variables, ingestion, local development, project layout, data model, Hub API client, and testing
- [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) — problem, roadmap, and trust bar for `/chat`
- [docs/adr/](docs/adr/) — architectural decision records
  - [ADR-0001](docs/adr/0001-llm-provider-strategy.md) — LLM provider strategy for the RAG generation layer
  - [ADR-0002](docs/adr/0002-retrieval-filtering-strategy.md) — retrieval filtering strategy
  - [ADR-0003](docs/adr/0003-structured-job-title-company-metadata.md) — structured job title/company metadata
  - [ADR-0004](docs/adr/0004-frontend-architecture-for-chat-interface.md) — frontend architecture for the chat interface
  - [ADR-0005](docs/adr/0005-visual-design-tokens-for-the-chat-ui.md) — visual design tokens for the chat UI
  - [ADR-0006](docs/adr/0006-chat-endpoint-hardening.md) — chat endpoint hardening
  - [ADR-0007](docs/adr/0007-local-generation-fallback-ollama-qwen3.md) — local generation fallback via Ollama
  - [ADR-0009](docs/adr/0009-grounded-inline-job-hyperlinks.md) — grounded inline job hyperlinks in generated answers
  - [ADR-0014](docs/adr/0014-embedding-model-migration.md) — E5-small via Qdrant Cloud Inference
