# Sentry: tracing and logs that changed Orbit

Orbit uses **Tracing** and **Logs**, in addition to error monitoring. Error breadcrumbs alone do not count as Logs. The Python SDK sends real `transaction` and `log` envelope items, and tests inspect both.

## What observability changed

The first instrumented workspace traces showed repeated reads of the same task, provider list, and facts. A blocked request made **14 SELECT queries** per snapshot. We reused the snapshot's loaded data when computing eligibility and its current proposal, reducing that to **8 SELECT queries**, with identical API responses. That is **43% fewer SELECTs** for this state. Pending and completed requests went from 11 to 8. These are local query counts, not a claim about production latency.

The before/after benchmark loads the previous workspace implementation from the explicitly selected trusted Git ref `c9f1ea8`, sends the same HTTP request to both implementations, compares their full responses, and counts SQL spans captured by Sentry. See [the captured evidence](sentry-evidence.json).

We also reproduced an offered-but-taken appointment. The correlated log has `within_window_count: 1`, `portal_count: 0`, and `matching_count: 0`: the provider's 3–4 p.m. offer fits the requested 2–5 p.m. window, but the portal cannot book it. The demo's per-request availability fix preceded this instrumentation; this replay of the condition demonstrates the diagnosis rather than claiming Sentry originally discovered it.

## Connect a project

The hosted Python/FastAPI project is `university-of-southern-cali-rg/orbit`, verified on October 17, 2026 (Pacific). The local ignored root `.env` contains its DSN, the `development` environment, and release `orbit@4867220`. The running backend on port 8000 has been restarted with this configuration. For another checkout, copy this project's DSN from **Settings → Projects → orbit → Client Keys (DSN)** into the root `.env`:

```dotenv
SENTRY_DSN=https://your-public-key@your-ingest-host/project-id
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=1.0
# Optional: deployment identifier
SENTRY_RELEASE=
```

Install the updated core requirements and restart the backend. `/health` reports whether Logs and Tracing are configured; this does not assert delivery. A DSN is sufficient for ingestion. An account API token is not required.

```sh
uv pip install --python .venv/bin/python -r backend/requirements/core.txt
```

Tracing samples all work by default for this demo; `SENTRY_TRACES_SAMPLE_RATE` accepts 0–1. Health checks and open event streams are excluded. Each worker tick is a short `orbit.workflow.tick` transaction, with `orbit.step` spans for individual operations. Waiting for human approval does not hold a trace open. `task_id` links requests, separate ticks, logs, and errors; concurrent tasks have isolated scopes. Application shutdown stops the worker and flushes the SDK's remaining log and event batches before uvicorn exits.

## Hosted verification

The synthetic demo sent **30 transactions and 76 logs**; all 32 ingestion requests returned HTTP 200. Sentry MCP queries then confirmed dashboard indexing, including **14 SELECT spans before and 8 after** the workspace optimization. The [committed evidence](sentry-evidence.json) records the accepted run and the separate dashboard verification.

- [Before: workspace trace with 14 SELECTs](https://university-of-southern-cali-rg.sentry.io/explore/traces/trace/4569bd4dd7fa45b9bc565ffcd8484e98)
- [After: workspace trace with 8 SELECTs](https://university-of-southern-cali-rg.sentry.io/explore/traces/trace/58bc03bda3024e19beac530ad7f606f0)
- [Offered-but-taken availability logs](https://university-of-southern-cali-rg.sentry.io/explore/logs/?project=4512274876465152&logsQuery=event%3Aavailability.checked%20task_id%3Atsk_9754b07b62614f29&statsPeriod=14d)
- [Lost-response reconciliation trace](https://university-of-southern-cali-rg.sentry.io/explore/traces/trace/4d50ff4a8744486f936dcb2bb0b4a6b3)
- [Error capture and readable source context: ORBIT-1](https://university-of-southern-cali-rg.sentry.io/issues/ORBIT-1)

A separate disposable uvicorn server loaded the real `app.main` initialization and lifespan, drove a fixture booking over HTTP to COMPLETED / PASS, and emitted a deliberate `RuntimeError: Orbit Sentry setup verification`. The captured stack includes its function, file, line, and source context. Its temporary error route and databases were removed; no diagnostic route was added to the demo backend. After fixing shutdown flushing, the final `booking.verified` log for `tsk_80e716f814eb484d` was confirmed in Sentry after the disposable server exited. These checks verify development telemetry; the workflow uses simulated providers and has not been deployed to production.

The synthetic test issue ORBIT-1 was resolved after verification. Its captured events remain available through the issue link above.

## Reproduce the submission evidence

From the repository root:

```sh
# Capture locally using the real SDK. No hosted Sentry connection required.
.venv/bin/python scripts/sentry_demo.py --baseline-ref c9f1ea8

# Send the same synthetic scenarios to the configured project.
.venv/bin/python scripts/sentry_demo.py --baseline-ref c9f1ea8 --send
```

The script uses temporary databases and real fixture messaging/browser adapters, coordinator, approval API, and verifier. It preserves the running app's data. It exercises:

1. Two separate runs booking the same sample slot successfully.
2. A provider offer inside the requested window with zero bookable portal slots.
3. A lost response after booking, followed by lookup and verification with exactly one stored booking.
4. Identical workspace responses before/after the query reduction.

Outputs are `artifacts/sentry/report.json` (SDK transactions/logs) and `artifacts/sentry/report.summary.json` (selected evidence). Local capture is labeled `local_capture`. `--send` records ingestion HTTP statuses and only labels the run `sentry_ingest_accepted` after successful HTTP responses. That label proves ingestion acceptance; dashboard indexing must be checked separately for each new run. The committed evidence includes the hosted run and its independent Sentry MCP verification. The separate normal-server check is saved locally in `artifacts/sentry/runtime-verification.json`.

## Show the judges

- In **Traces**, inspect `/tasks/{task_id}` before/after using the trace IDs in the report. Expand the SQL spans and show the repeated task/provider/fact reads disappearing.
- In **Logs**, filter `event:availability.checked`, then `task_id:<id from report>`. Show offered, within-window, portal, and matching counts. Open the linked trace to inspect the actual availability step.
- For the lost-response scenario, filter by its task ID. Show `booking.ambiguous`, the `reconcile_booking` span, the PASS verdict in `booking.verified`, and the report's single stored booking.

Suggested narration: “Tracing exposed repeated reads in our workspace snapshots. We cut the blocked view from 14 SELECTs to 8 while preserving the full response. Logs tell us whether an offered appointment fits the user's window but disappeared from the portal, and link to the exact workflow step. When a booking response is lost, the trace shows a lookup before any resubmission.”

## Collected data and validation

Logs carry operational IDs, counts, durations, outcomes, and verdicts. They exclude provider message bodies, customer details, request bodies/headers/cookies/query values, SQL parameters, AI inputs/outputs, and frame locals. Error, trace, and log payloads have separate scrubbers. Only Orbit loggers are forwarded. Business outcomes such as a rejected proposal or unavailable slot remain Logs rather than error issues.

The regression suite checks actual SDK envelope types, log-to-span correlation, parallel task isolation, privacy filtering, absence of repeated snapshot reads, and existing approval/completion gates:

```sh
cd backend
../.venv/bin/python -m pytest -q tests ../portal/tests
```

Implementation references: [Sentry Python Logs](https://docs.sentry.io/platforms/python/logs/), [custom tracing](https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation/). Orbit requires `sentry-sdk>=2.72.0,<3` and uses the current logging integration options.
