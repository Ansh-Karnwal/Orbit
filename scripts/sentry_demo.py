"""Exercise real fixture workflows and capture Sentry Tracing + Logs.

Run from the repo root: .venv/bin/python scripts/sentry_demo.py
Add --send to deliver to SENTRY_DSN. Uses temporary databases, never the running demo's data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "portal")]
os.environ.update({"ORBIT_MODE": "fixture", "MESSAGING_MODE": "fixture",
                   "BROWSER_MODE": "fixture", "LLM_MODE": "fixture"})

import httpx  # noqa: E402
import sentry_sdk  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sentry_sdk.transport import HttpTransport, Transport  # noqa: E402

from app.adapters import registry  # noqa: E402
from app.adapters.fixture_browser import FixtureBrowserAdapter  # noqa: E402
from app.adapters.fixture_messaging import FixtureMessagingAdapter  # noqa: E402
from app.core import coordinator, db, repo, telemetry  # noqa: E402
from app.core.api import tasks  # noqa: E402
from app.core.api.demo import resolve_seed  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.inbound import handle_inbound  # noqa: E402
from app.core.logs import setup_logging  # noqa: E402
from portal_core import create_app  # noqa: E402


class ReportingHttpTransport(HttpTransport):
    """Record ingestion HTTP status; a 2xx confirms acceptance, not dashboard indexing."""
    def __init__(self, options):
        super().__init__(options)
        self.status_codes = []

    def _request(self, *args, **kwargs):
        response = super()._request(*args, **kwargs)
        self.status_codes.append(response.status)
        return response


class CaptureTransport(Transport):
    send = False

    def __init__(self, options):
        super().__init__(options)
        self.traces = []
        self.logs = []
        self.errors = []
        self.network = ReportingHttpTransport(options) if self.send else None

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type in {"transaction", "event", "log"}:
                payload = json.loads(item.get_bytes())
                if item.type == "transaction":
                    self.traces.append(payload)
                elif item.type == "event":
                    self.errors.append(payload)
                else:
                    self.logs.extend(payload["items"])
        if self.network:
            self.network.capture_envelope(envelope)

    def flush(self, timeout, callback=None):
        if self.network:
            self.network.flush(timeout, callback)

    def kill(self):
        if self.network:
            self.network.kill()


class ConnectedTransport(CaptureTransport):
    send = True


async def drive(task_id, expected):
    for _ in range(100):
        await coordinator.tick(task_id)
        task = repo.get_task(task_id)
        if task.status == expected:
            return task
        if task.status in {"FAILED", "CANCELLED", "BLOCKED"}:
            raise RuntimeError(f"Expected {expected}, got {task.status} for {task_id}")
        await asyncio.sleep(0.01)
    raise RuntimeError(f"Workflow did not reach {expected}: {task_id}")


def select_count(trace):
    return sum(span.get("op", "").startswith("db") and span.get("description", "").startswith("SELECT")
               for span in trace["spans"])


def benchmark(client, task_id, capture, baseline_ref):
    # Only execute a baseline the operator explicitly selects from this trusted local repository.
    source = subprocess.run(["git", "show", f"{baseline_ref}:backend/app/core/api/views.py"],
                            cwd=ROOT, check=True, capture_output=True, text=True).stdout
    baseline = ModuleType("orbit_workspace_baseline")
    exec(compile(source, f"{baseline_ref}:views.py", "exec"), baseline.__dict__)
    with patch.object(tasks, "build_view", baseline.build_view):
        before = client.get(f"/tasks/{task_id}")
    before_trace = capture.traces[-1]
    after = client.get(f"/tasks/{task_id}")
    after_trace = capture.traces[-1]
    assert before.status_code == after.status_code == 200
    assert before.json() == after.json(), "The optimization must preserve the full TaskView"
    return {"baseline_ref": baseline_ref, "before_selects": select_count(before_trace),
            "after_selects": select_count(after_trace), "responses_identical": True,
            "before_trace_id": before_trace["contexts"]["trace"]["trace_id"],
            "after_trace_id": after_trace["contexts"]["trace"]["trace_id"]}


def summary(report):
    measurement = report["workspace_benchmark"]
    trace_ids = {measurement[key] for key in ("before_trace_id", "after_trace_id")} if measurement else set()
    traces = []
    for trace in report["transactions"]:
        trace_id = trace["contexts"]["trace"]["trace_id"]
        if trace_id in trace_ids:
            queries = [span["description"] for span in trace["spans"]
                       if span.get("description", "").startswith("SELECT")]
            traces.append({"trace_id": trace_id, "transaction": trace["transaction"],
                           "select_count": len(queries),
                           "query_tables": [re.search(r"FROM (\w+)", query)[1] for query in queries]})
    logs = [{"body": item["body"], "trace_id": item.get("trace_id"), "span_id": item.get("span_id"),
             "attributes": {key: value["value"] for key, value in item["attributes"].items()
                            if key in telemetry.ATTRIBUTES}}
            for item in report["logs"]
            if item["body"] in {"availability.checked", "booking.ambiguous", "booking.verified"}]
    return {"source": "Captured Sentry SDK envelopes; delivery field distinguishes local and hosted runs",
            "delivery": report["delivery"], "ingest_http_statuses": report["ingest_http_statuses"],
            "counts": report["counts"], "scenarios": report["scenarios"],
            "workspace_benchmark": measurement, "workspace_traces": traces, "log_samples": logs}


async def exercise(temp, capture, baseline_ref):
    settings = get_settings()
    settings.database_url = f"sqlite:///{temp / 'orbit.db'}"
    settings.artifact_dir = str(temp / "artifacts")
    settings.portal_base_url = "http://portal.test"
    settings.sentry_traces_sample_rate = 1.0
    db.init_db()
    portal_app = create_app(temp / "portal.db")
    portal_transport = httpx.ASGITransport(app=portal_app)
    messaging = FixtureMessagingAdapter(time_scale=0)
    registry._messaging = messaging
    await messaging.start(handle_inbound)
    app = FastAPI()
    app.include_router(tasks.router)
    client = TestClient(app)
    scenarios = []

    async with httpx.AsyncClient(transport=portal_transport, base_url="http://portal.test") as portal:
        browser = FixtureBrowserAdapter(client=portal)
        registry._browser = browser
        seed = resolve_seed("fixture")

        def new_task():
            response = client.post("/tasks", json=seed.model_dump(mode="json"))
            assert response.status_code == 201
            return response.json()["task"]["id"]

        def approve(task_id):
            approval = repo.get_latest_approval(task_id)
            response = client.post(f"/tasks/{task_id}/approvals", json={
                "proposal_hash": approval.proposal_hash, "decision": "approved"})
            assert response.status_code == 200

        for run in range(2):
            task_id = new_task()
            await drive(task_id, "AWAITING_APPROVAL")
            proposal = repo.get_latest_approval(task_id).proposal
            approve(task_id)
            await drive(task_id, "COMPLETED")
            scenarios.append({"scenario": "repeat_booking", "run": run + 1, "task_id": task_id,
                              "status": "COMPLETED", "slot_start": proposal.slot_start.isoformat()})
        assert scenarios[0]["slot_start"] == scenarios[1]["slot_start"]

        # Deliberately consume this run's sample slots: provider messages still offer them.
        task_id = new_task()
        day = seed.constraints.window_start.astimezone(ZoneInfo(seed.constraints.timezone)).date()
        for provider in seed.providers:
            slots = (await portal.get(f"/api/p/{provider.id}/slots", params={
                "date": day.isoformat(), "demo_run_id": task_id})).json()["slots"]
            for slot in slots:
                response = await portal.post(f"/api/p/{provider.id}/book", json={
                    "slot_start": slot["start"], "service": seed.constraints.service,
                    "customer_name": "Demo", "customer_contact": "demo@example.test",
                    "reference": "deliberately_taken", "demo_run_id": task_id})
                assert response.status_code == 201
        await drive(task_id, "BLOCKED")
        scenarios.append({"scenario": "offered_but_taken", "task_id": task_id, "status": "BLOCKED"})
        measurement = benchmark(client, task_id, capture, baseline_ref) if baseline_ref else None

        # Lose the response after the portal records the booking. Recovery must look it up.
        async def lose_response(request):
            response = await portal_transport.handle_async_request(request)
            if request.method == "POST" and request.url.path.endswith("/book"):
                await response.aread()
                raise httpx.ReadTimeout("Simulated lost booking response", request=request)
            return response

        async with httpx.AsyncClient(transport=httpx.MockTransport(lose_response)) as interrupted:
            registry._browser = FixtureBrowserAdapter(client=interrupted)
            task_id = new_task()
            await drive(task_id, "AWAITING_APPROVAL")
            approve(task_id)
            await drive(task_id, "COMPLETED")
            bookings = [b for b in portal_app.state.store.bookings() if b["demo_run_id"] == task_id]
            assert len(bookings) == 1, "Reconciliation must not submit a duplicate booking"
            scenarios.append({"scenario": "lost_response_reconciled", "task_id": task_id,
                              "status": "COMPLETED", "bookings": len(bookings)})
    await messaging.stop()
    client.close()
    return scenarios, measurement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Send synthetic demo telemetry to SENTRY_DSN")
    parser.add_argument("--verbose", action="store_true", help="Also print each structured operation locally")
    parser.add_argument("--baseline-ref", help="Trusted local Git ref for before/after workspace tracing (e.g. c9f1ea8)")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/sentry/report.json")
    args = parser.parse_args()
    settings = get_settings()
    if args.send and not settings.sentry_dsn:
        parser.error("Set SENTRY_DSN in the root .env before using --send")
    setup_logging()
    if not args.verbose:
        for handler in logging.getLogger("orbit").handlers:
            handler.setLevel(logging.WARNING)
    telemetry.init(settings.sentry_dsn if args.send else "https://public@sentry.invalid/1",
                   transport=ConnectedTransport if args.send else CaptureTransport)
    capture = sentry_sdk.get_client().transport
    try:
        with TemporaryDirectory(prefix="orbit-sentry-") as temp:
            scenarios, measurement = asyncio.run(exercise(Path(temp), capture, args.baseline_ref))
        sentry_sdk.flush(timeout=10)
        statuses = capture.network.status_codes if capture.network else []
        accepted = bool(statuses) and all(200 <= status < 300 for status in statuses)
        report = {"delivery": "sentry_ingest_accepted" if args.send and accepted else "local_capture",
                  "ingest_http_statuses": statuses, "scenarios": scenarios, "workspace_benchmark": measurement,
                  "counts": {"transactions": len(capture.traces), "logs": len(capture.logs), "errors": len(capture.errors)},
                  "transactions": capture.traces, "logs": capture.logs}
        assert report["counts"]["transactions"] > 0 and report["counts"]["logs"] > 0
        for item in (item for item in capture.logs if item["body"] == "availability.checked"):
            trace = next(t for t in capture.traces if t["contexts"]["trace"]["trace_id"] == item["trace_id"])
            assert any(span["span_id"] == item["span_id"] for span in trace["spans"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=str) + "\n")
        args.out.with_suffix(".summary.json").write_text(json.dumps(summary(report), indent=2) + "\n")
        print(json.dumps({"report": str(args.out), "delivery": report["delivery"],
                          "counts": report["counts"], "workspace_benchmark": measurement}))
        if args.send and not accepted:
            raise SystemExit("Sentry ingestion was not confirmed; inspect SDK/network settings and the local report")
    finally:
        telemetry.shutdown()


if __name__ == "__main__":
    main()
