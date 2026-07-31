# Grafana Cloud: prompt-injection alerting (ADR-0015)

Companion runbook for [ADR-0015](../adr/0015-observability-logging-and-alerting.md) Decisions 5–6.
Alert configuration lives in Grafana Cloud (no Collector / no self-hosted stack).

## Prerequisites

1. Grafana Cloud free-tier stack with Loki enabled.
2. Access policy / API token with `logs:write`.
3. App and ingestion configured with all three env vars (see `.env.example`):
   - `GRAFANA_LOKI_URL` — push endpoint (`…/loki/api/v1/push`)
   - `GRAFANA_LOKI_USER_ID` — Loki user / instance ID (basic-auth username)
   - `GRAFANA_LOKI_API_KEY` — access policy token (basic-auth password)
4. Same three secrets on Render (API) and as GitHub Actions secrets for `ingest.yml`.

Structured logs set Loki labels `event` and `source` (via `props_to_labels`), plus `app=hubster`.

## Contact point (email)

1. Grafana Cloud → **Alerting** → **Contact points** → **Add contact point**.
2. Type: **Email**. Address: the on-call / maintainer inbox.
3. Save (e.g. name `hubster-email`).

## Alert rule

1. **Alerting** → **Alert rules** → **New alert rule**.
2. Query type: **LogQL** against the Loki datasource.
3. Query (matches ingestion and `/chat` user-query detections):

```logql
count_over_time({app="hubster", event="injection_detected"}[5m]) > 0
```

Equivalent explore filter for debugging:

```logql
{app="hubster", event="injection_detected"}
```

Inspect `source` (`ingestion` | `user_query`), `pattern`, and (when present) `job_id` / `question` in the JSON log line.

4. **Evaluation interval:** `1m` or `5m` — short enough that user-query hits are not delayed to the daily ingestion cadence. Do **not** evaluate only once per day.
5. Pending period: `0` or `1m` (fire as soon as a match appears in the window).
6. Labels / annotations: optional `severity=warning`, summary mentioning `injection_detected`.
7. Notification: contact point `hubster-email`.

## Verify

1. Trigger a `/chat` request whose question contains a known pattern (e.g. `ignore previous instructions`) — response must still be a normal 200/generated answer (log-only).
2. Confirm a Loki line with `event=injection_detected`, `source=user_query`.
3. Confirm the alert transitions to firing within one evaluation interval.
4. Optionally run ingestion against a fixture job with injection phrasing and confirm `source=ingestion`.

## Related

- [/chat observability dashboard](grafana-cloud-chat-observability.md) — request volume, errors, latency, provider, and injection panels over the same Loki stream.
