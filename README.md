# Hubster

![Tests](https://github.com/alexmonteirocastro/hubster/actions/workflows/test.yml/badge.svg)

Hubster ingests job listings from [The Hub](https://thehub.io/) via their public API, embeds the content with FastEmbed, and stores the results in [Qdrant](https://qdrant.tech/) for semantic search — with a `/chat` RAG layer and React UI for natural-language job discovery across Nordic/European startup markets.

## Quick start (Docker)

### 1. Configure environment

```bash
cd hubster
cp .env.example .env
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#environment-variables) for the full variable reference.

### 2. Start the stack

```bash
docker compose up --build
```

This starts:

- **qdrant** — vector database on `localhost:6333` (persisted volume)
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
| `POST /chat` | Single-turn RAG chat: retrieve jobs from Qdrant, then generate a grounded answer via the `Generator` interface (Gemini 2.5 Flash by default). **Request:** `question` (required, max **500** characters — bounds token cost and latency before any retrieval or generation), optional `limit` (default 5), optional `country` (`DK`, `SE`, `NO`, `FI`, `IS`, `EU`), optional `remote` (`true` = remote only, `false` = on-site only). When `country`/`remote` are omitted, `/chat` infers them from the question text via deterministic keyword matching; explicit request fields always override inferred values. **Rate limit:** per-client in-memory limit on `/chat` only (default **10 requests/minute**; returns 429 when exceeded). `/jobs/search` and `/jobs/stats` are not rate-limited. Override via `CHAT_QUESTION_MAX_LENGTH` and `CHAT_RATE_LIMIT` in `.env`. **Response:** `question`, `answer`, `sources` (retrieved job hits with scores), `generated` (`true` when the LLM produced the answer), `applied_country` / `applied_remote` (the filters actually used for retrieval — `null` when nothing was resolved). See [ADR-0001](docs/adr/0001-llm-provider-strategy.md) and [ADR-0002](docs/adr/0002-retrieval-filtering-strategy.md). |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs) when the `api` service is running.

## Dev workflow

See [CONTRIBUTING.md](CONTRIBUTING.md#code-quality) for Ruff, mypy, oxlint, pre-commit setup, and the CI checks to run locally before opening a PR.

## Where to go next

- [CONTRIBUTING.md](CONTRIBUTING.md) — code-quality tooling and dev checks
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — environment variables, ingestion, local development, project layout, data model, Hub API client, and testing
- [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) — problem, roadmap, and trust bar for `/chat`
- [docs/adr/](docs/adr/) — architectural decision records
