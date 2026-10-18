How Orbit decides
=================

Orbit stores each provider claim with its source and keeps previous versions when terms change.
It compares only complete, consistent quotes inside the user's time window and total visit budget.
Approval binds a specific provider, appointment, price, fee scope and cancellation policy.
An independent verifier checks booking evidence against those exact approved terms using deterministic predicates.
Orbit says “Booking verified” only after PASS, labels fixture evidence, and states when parts and labor remain unknown.

Verifier predicates
===================

| Predicate | Required evidence or condition |
| --- | --- |
| provider_identified | Confirmation identifies the approved provider. |
| service_matches | User, approval and confirmation services agree. |
| slot_within_window | Confirmation slot is fully inside the user's window. |
| charge_within_budget | Confirmation total visit charge is within budget. |
| fee_scope_clear | Approved scope and required diagnostic fee are confirmed. |
| cancellation_terms_present | Required terms appear in approval and confirmation. |
| approval_matches_current_proposal | Approved, unexpired hash still matches current facts. |
| confirmation_present | Portal confirmation has an id and matches the approval-bound orbit_ref. |
| confirmation_consistent | Provider, service, slot, charge, cancellation terms and orbit_ref match exactly. |

Any false predicate means FAIL; otherwise any missing predicate means INSUFFICIENT_EVIDENCE; otherwise PASS.
The LLM can explain a verdict but cannot determine or change it. `verify()` does not persist its result.

Integration dependencies
========================

Victor's CP0 at `e5b0a30d35554de28c450e002ceb9db871e298a6` is imported locally. These modules use its actual shared schemas; there are no duplicate shared models here.
The published `repo.py` and `db.py` still raise `NotImplementedError`, so the real SQLite integration run awaits Victor's implementation.
`facts.py` accepts inbound ids by prefix if CP0 has no inbound lookup, as permitted by the brief. Evidence ids must resolve to evidence for the same task.
If `repo.get_inbound()` becomes available, it is used for source validation and original receipt timestamps.
The core worker must serialize fact ingestion per task: the shared repo interface does not provide an atomic compare-and-supersede operation.

**Coordinator wiring required:** `app.context.booking.record_booking_request(request)` now captures the approval/reference link using the existing shared `BookingRequest` schema.
It checks the current granted approval and exact proposal hash, records a separate `browser_trace` artifact, and omits customer contact data.
Repeating the same request reuses the artifact. A different reference for the same approval is rejected so the caller must reconcile the existing booking.
Victor should call it immediately before the browser action, after deriving the durable reference:

```python
from app.context.booking import record_booking_request

# request is the existing shared BookingRequest; keep its orbit_ref on all retries.
record_booking_request(request)
result = await browser.submit_booking(request)
```

This is an additional helper, with no changes to shared schemas or existing cross-module signatures.
The core coordinator remains Victor's untouched stub, so this call has not been inserted into production orchestration.
Missing or conflicting request evidence yields INSUFFICIENT_EVIDENCE. A confirmation cannot establish its own approval link.
Confirmations captured before the recorded request are excluded; newer contradictory or malformed confirmations cannot be hidden by older successful evidence.

Validation
==========

From the repository root:

```sh
PYTHONPATH=backend python3 -m pytest backend/tests/context backend/tests/verify -q
```

Validation against the published CP0: **113 passed, 4 skipped** through `make test PY=python3`.
All acceptance scenarios run using `tests/context/fakes.py` and Victor's actual shared Pydantic models.
`test_fixture_workflow.py` also exercises the published messaging and browser adapters, inquiry/reply ingestion, $120→$190 fact supersession, approval invalidation, $145 B selection, portal availability facts, approved request capture, idempotent booking/reconciliation, read-only PASS verification, and the honest final summary.
This is an offline integration check with the fake repo; it does not exercise Victor's unfinished coordinator, SQLite persistence, or the real portal.
The four live LLM cases are intentionally skipped at the user's request. They are no longer a requested completion requirement.
Real SQLite/coordinator/portal integration remains pending because their published implementations are stubs.
Other owners' upstream files are unchanged. Publish these changes on `karthik/context`; keep integration work in the relevant owners' modules.

| Criterion | Tests |
| --- | --- |
| A2 | test_facts.py: source required, existing evidence, no unproven facts |
| A3 | test_facts.py, test_proposals.py, test_extract_ingest.py: $120→$190 versions and B selection |
| A7 | test_approval_validity.py and test_booking.py: material changes, expiration and enforcement before request capture |
| A8 | test_verifier.py: missing, malformed or pre-request confirmation; missing independent booking reference |
| A9 | test_verifier.py: mismatched charge, slot, provider, service, terms or reference; newer mismatches override older matching evidence |
| A10 | test_verifier.py and test_fixture_workflow.py: matching PASS; test_summary.py: honest diagnostic-only summary |

Environment
===========

Offline: `LLM_MODE=fixture` (default). No API key or SDK import is required for the fixture path.
Live: `LLM_MODE=live`, `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.8-flash`, `GEMINI_API_KEY=<secret>`.
`app.llm.client.status()` supplies fixture/live/blocked status for the adapter registry.
Install `backend/requirements/context.txt` alongside Victor's core requirements.
The client reads Victor's shared `.env` settings, with process environment variables taking precedence.
The SDK API was checked against [Anthropic's structured output docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) and its [official source](https://github.com/anthropics/anthropic-sdk-python).
Live execution was skipped at the user's request. Offline SDK mocks cover validation retries, transport retries, budget accounting, and prompt-injection boundaries including validation feedback.

To opt into paid live tests with your configured model:

```sh
RUN_LIVE_LLM_TESTS=1 PYTHONPATH=backend python3 -m pytest backend/tests/context/test_live_llm.py -q
```

Suggested review sequence
=========================

1. `[context] Add versioned home repair domain pack and normalization`
2. `[context] Add provenanced fact versions and constraint conflicts`
3. `[llm] Add structured Anthropic client with offline fallback and injection boundaries`
4. `[context] Add quote extraction, composition and exact proposal approvals`
5. `[verify] Add read-only deterministic booking verification`
6. `[context] Add scoped context packets, honest summary and acceptance tests`
