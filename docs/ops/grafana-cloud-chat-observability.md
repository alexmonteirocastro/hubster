# Grafana Cloud: /chat observability dashboard (ADR-0015)

Companion runbook for [ADR-0015](../adr/0015-observability-logging-and-alerting.md) structured logs shipped by [ALE-162](https://linear.app/alex-projects/issue/ALE-162). Builds on the injection alert setup in [grafana-cloud-injection-alerting.md](grafana-cloud-injection-alerting.md).

Dashboard JSON (importable): [`grafana-dashboards/chat-observability.json`](grafana-dashboards/chat-observability.json).

## Prerequisites

1. Loki push working (all three `GRAFANA_LOKI_*` env vars on the API / ingestion — see `.env.example`).
2. Grafana Cloud stack with the Loki datasource already available (same stack used for the injection alert).
3. At least a few real `chat_request` / `injection_detected` lines in Loki (Explore with `{app="hubster"}`).

## Import

1. Grafana Cloud → **Dashboards** → **New** → **Import**.
2. Upload `docs/ops/grafana-dashboards/chat-observability.json` (or paste its contents).
3. When prompted, select your **Loki** datasource for the `datasource` variable (or pick it from the dashboard dropdown after import).
4. Save. UID is fixed as `hubster-chat-observability` so re-import updates the same dashboard.

## Panels

| Panel | LogQL (simplified) | Source fields |
|-------|--------------------|---------------|
| Request volume | `sum(count_over_time({app="hubster", event="chat_request"}[$__auto]))` | Loki label `event` |
| Error rate by `error_type` | `… event="chat_request" \| json \| status="error"` then `sum by (error_type)` | JSON `status`, `error_type` |
| Latency p50 / p95 | `quantile_over_time(0.50\|0.95, … \| json \| unwrap latency_ms [$__auto])` | JSON `latency_ms` |
| Provider breakdown | `sum by (provider) (count_over_time(… \| json \| provider != "" …))` | JSON `provider` |
| Injection detections by source | `sum by (source) (count_over_time({app="hubster", event="injection_detected"}[$__auto]))` | Loki labels `event`, `source` |

Injection panel selector matches the existing alert rule family (`event="injection_detected"`); see [grafana-cloud-injection-alerting.md](grafana-cloud-injection-alerting.md).

## Verify against live traffic

With Loki credentials configured on the deployed API:

1. **Volume + provider** — send several normal `/chat` questions; confirm **Request volume** and **Provider breakdown** move (provider matches `LLM_PROVIDER`).
2. **Latency** — confirm p50/p95 update (values in ms).
3. **Error** — induce a distinguishable failure (e.g. temporarily force a Gemini rate-limit or point at a broken generator config); confirm **Error rate by error_type** shows the expected `error_type` (e.g. `GenerationRateLimitError`), not a generic bucket.
4. **Injection** — send a `/chat` question containing `ignore previous instructions`; confirm a normal answer still returns, and **Injection detections by source** shows `user_query`.

If panels are empty: open **Explore**, run `{app="hubster"}`, and confirm lines exist. Check that `event` appears as a **label** (from `props_to_labels`) and that the log line body is JSON parseable with `| json`.
