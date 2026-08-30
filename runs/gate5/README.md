# Gate 5 evidence — ingest service, one tenant, one feed

Gate 5's criterion is *"run locally against the live feed for one hour. Record parse
failure rate, duplicate rate, and bytes saved by conditional requests."*

| File | What it shows |
|---|---|
| `predictions.txt` | The seven predicted values, and the recomputation that corrected one of them, captured as program output. The predictions themselves are in `docs/metrics.md`, committed before the run. |
| `tests-fail-first.txt` | Every gate this service adds, verified by breaking it. Seven mutations, seven suite failures, clean controls either side. |
| `decode-bench-container.txt` | The memory sizing term, measured by RSS inside a Linux container. |
| `hour-run-report.json` | The verification run's structured report. |
| `hour-run-console.txt` | What the run printed while it ran. |
| `hour-run-database.txt` | The same run read back out of Postgres, which is a different question from what the counters say. |

`blobs/` holds three real Stage 0 payloads used as benchmark input. Gitignored, like every
other captured payload in this repo.

## What this gate does NOT claim

- **Nothing here has been deployed.** No Helm chart, no image push, no Kubernetes, no
  ArgoCD. Gate 6 is packaging and it has not started.
- **No Prometheus, no OpenTelemetry, no `/metrics` endpoint.** Observability is Gate 7's
  decision and importing a metrics client now would pre-empt it. The numbers here come from
  in-process counters and from Postgres.
- **No SLIs and no SLOs.** Gate 8. The outcome taxonomy in `ingest/run.py` is written so
  SLI 1 has something honest to read later, and that is all it is.
- **One tenant.** Multi-tenancy is Stage 2. The tenant file is the source of truth PLAN.md
  section 3 describes, with exactly one consumer.
- **An hour supports no availability claim**, exactly as Stage 0 recorded. Nothing in the
  report should be read as one.
