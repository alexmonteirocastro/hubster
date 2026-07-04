# Hubster

Hubster ingests job listings from [The Hub](https://thehub.io/) via their public API, embeds the content with FastEmbed, and stores the results in [Qdrant](https://qdrant.tech/) for semantic search.

Use it to build job-discovery tools, RAG chatbots, or analytics over Nordic/European startup job markets.

## Features

- **API-based ingestion** — fetches paginated job listings and full job details from The Hub REST API
- **Multi-country support** — Denmark, Sweden, Norway, Finland, Iceland, and Europe
- **Vector storage** — embeds job title, company info, and descriptions into Qdrant
- **Semantic search** — query jobs by natural language (e.g. "Python developer in Denmark")
- **Optional CSV export** — dump scraped jobs to `tmp/jobs_preview.csv`
- **Streamlit dashboard** — explore job counts by role and country (chat UI is a work in progress)

## How it works

1. For each supported country, Hubster calls `/api/v2/jobs` to discover all job IDs (paginated).
2. For each ID, it fetches `/api/jobs/single/{id}` and maps the response to a `JobOpportunity` model.
3. HTML fields are converted to Markdown.
4. A document string is built from the job title, company name, company description, and job description.
5. Qdrant (via `qdrant-client[fastembed]`) embeds the text with `BAAI/bge-small-en-v1.5` and upserts points with metadata (role, location, remote, salary, equity, etc.).

## Requirements

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running Qdrant instance (local or cloud)

## Quick start

### 1. Clone and install

```bash
cd hubster
uv sync
# or: pip install -e .
```

### 2. Start Qdrant locally

Using Docker:

```bash
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_data:/qdrant/storage" \
  qdrant/qdrant
```

Qdrant will be available at `http://localhost:6333`.

### 3. Configure environment

Copy the example env file and set your values:

```bash
cp .env.example .env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `QDRANT_COLLECTION_NAME` | Qdrant collection name | `JOBS_ON_THE_HUB` |
| `EMBEDDING_MODEL` | FastEmbed model ID | `BAAI/bge-small-en-v1.5` |

> **Note:** The Qdrant URL is currently hardcoded in `db/database.py` (`http://localhost:6333`). For Qdrant Cloud, uncomment and configure the cloud client there.

### 4. Run the scraper

```bash
uv run python main.py
```

This will:

1. Drop the existing collection (see note below)
2. Create the collection if missing
3. Scrape all jobs across supported countries
4. Ingest them into Qdrant
5. Run a sample semantic search

> **Warning:** `main.py` currently calls `main(reset_db=True)`, which **deletes the collection before each run**. Change to `main(reset_db=False)` for incremental updates.

### 5. Launch the Streamlit app (optional)

```bash
uv run streamlit run streamlit_app.py
```

- **Jobs tab** — live stats from The Hub API (totals and breakdown by role)
- **Chat tab** — placeholder demo; not yet wired to Qdrant

## Project structure

```
hubster/
├── main.py                 # Scrape, seed Qdrant, test search
├── streamlit_app.py        # Simple dashboard / demo UI
├── the_hub_client/
│   ├── models.py           # Pydantic models (JobOpportunity, CountryCode, …)
│   └── utils.py            # The Hub API client
├── db/
│   ├── database.py         # Qdrant client, collection CRUD, embedding, search
│   └── db_utils.py         # seed_qdrant_db(), CSV export
├── pyproject.toml
└── .env.example
```

## Stored data

Each Qdrant point includes:

**Embedded text**

```
Job Title: …
Company: …
Company Description: …
Job Description: …
```

**Payload metadata**

- `job_url_identifier`, `job_role`, `Country`, `location`, `Remote`
- `Salary Type`, `Salary`, `Equity`
- `document_text` (full embedded string)

Point IDs are deterministic UUID5 values derived from the Hub job ID.

## Programmatic usage

```python
from db import client, create_collection, query_jobs_in_qdrant

create_collection(client, "JOBS_ON_THE_HUB")

results = query_jobs_in_qdrant(
    db_client=client,
    collection_name="JOBS_ON_THE_HUB",
    query_text="Looking for a Python developer in Denmark",
)

for hit in results.points:
    print(hit.score, hit.payload["job_role"])
```

Export to CSV instead of Qdrant:

```python
from db import load_jobs_data_into_csv

load_jobs_data_into_csv("jobs_preview.csv")  # writes to tmp/
```

## The Hub API endpoints used

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/jobs?countryCode={code}&page={n}` | Paginated job listings |
| `GET /api/jobs/single/{job_id}` | Full job details |

Base URL: `https://thehub.io`

## Roadmap / known limitations

- [ ] Wire Streamlit chat to Qdrant semantic search (RAG)
- [ ] Move Qdrant URL / API key to environment variables
- [ ] Incremental sync (skip already-ingested jobs instead of full reset)
- [ ] Remove unused `chromadb` dependency
- [ ] Rate limiting and retry logic for API calls
