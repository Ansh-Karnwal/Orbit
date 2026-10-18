# Orbit — plan and current limits

*As of Sat 2026-10-17 evening, before the Sunday 9:30 a.m. feature freeze. Owner: Victor (contract keeper). Changes to `schemas.py`, the HTTP API or the fact keys go through team agreement first (§5).*

Orbit today runs the canonical story end to end in fixture mode: two providers quote, Ace's price changes, Orbit withdraws the approval, replans to Bayside, books it, and the independent verifier passes it. This document lists what the system can't do yet and the plan for seven requested capabilities:

1. Re-coordinating other options when the user rejects a proposal.
2. More than two providers.
3. A sliding provider gallery for the current sandbox.
4. A room for managing searches beyond dishwasher repair.
5. Room for sign-in.
6. Room for consistent errors and case states.
7. A real Photon loop: message, receive, summarize, report.

---

## 0. Execution status (Sat evening) — read this first

All seven workstreams and the six core gaps are implemented and tested, except a live Photon run (G1). Every change is additive: the canonical two-provider story, its tests and the demo script still work unchanged. **The §5 contract changes are in `schemas.py` and need the team's review.** Teammates' areas were edited (context, adapters, portal data, frontend), so please review your own files.

| Item | Status | Where | Proven by |
|---|---|---|---|
| A. Reject → find another | ✅ Reject records a `user_decision` evidence + fact (`declined_by_user` or `declined_slots`); Orbit replans to the next option; if none is left it asks (`user_rejected_all` / `no_eligible_provider`). UI: **Not this one — find another**, **A different time**, **Stop here**. | `core/approvals.py`, `context/decisions.py`, `ApprovalCard.tsx` | `test_coordinator::test_rejecting_finds_another_option…`, `test_reject_answers.py`, UI drive |
| B. More than two providers | ✅ Up to 10; intake adds or removes providers (sandbox catalog or custom); sandbox gains **Coastal Appliance Pros** (`provider_c`, $160) in the seed file's extras, portal and fixture script; presenter can inject a message from any provider. | `demo/seed.json`, `portal/providers.yaml`, `demo/fixture_script.json`, `Intake.tsx`, `DemoPanel.tsx` | `test_services_providers.py::test_three_providers_story`, UI drive |
| C. Sliding gallery | ✅ Scroll-snap carousel, left to right (proposal → eligible by price → waiting → out); arrows, dots, ←/→; auto-slides when there are more than 2 providers, pauses on hover or focus, off with reduced motion; per-provider summary line. | `ProviderGallery.tsx` | `roadmap.test.tsx`, screenshots |
| D. Services room | ✅ `/services` page with catalog + searches grouped by state and filtered by service; `GET /services`, `GET /tasks?service=&status=`, `GET /demo/seed?service=`; second service **washer_repair** (pack services + synonyms, parser, portal, fixture replies). | `ServicesRoom.tsx`, `context/domain.py`, `parser.py`, `api/tasks.py` | `test_services_providers.py`, washer UI drive |
| E. Sign-in room | ✅ Demo sign-in (name only, httpOnly session cookie); every task route scoped to its owner (others get 404); approver taken from the session; `ORBIT_AUTH_MODE=required` returns 401. `/signin` page and header chip. | `core/auth.py`, `SignIn.tsx`, `SiteHeader.tsx` | `test_auth_errors.py` |
| F. Errors & case states | ✅ One error envelope (legacy `detail` kept); `Task.reason_code` on every status; every BLOCKED path asks a question with options; `POST /tasks/{id}/answers` (raise budget, widen window, reconsider, add provider, try again, check again, extend limits, stop). Blocked tasks pause until answered. UI question card. | `core/errors.py`, `questions.py`, `answers.py`, `QuestionCard.tsx` | `test_reject_answers.py`, `test_auth_errors.py` |
| G. Photon | 🟡 G2–G4 done: `user_contact` reports (approval, question, completion) once per event; per-provider summaries; text approvals (`YES <hash8>`) behind `ORBIT_TEXT_APPROVALS`, owner handle only; "must text first" → `integration_blocked` question, never a retry loop. **G1 not run live:** needs a Photon Beta key and project, plus consenting teammates' handles. `photonhq-api==0.5.0` is now installed and its adapter tests pass. | `coordinator._send_reports`, `inbound.py`, `adapters/photon.py` | `test_reports.py`, `test_reject_answers::test_must_text_first…` |
| Core gaps (a)–(f) | ✅ (a) `repo.get_inbound` lets older messages be stored as `rejected`; (b) late-message extraction backs off and asks after 3 failures; (c) budget gate before every wave, no overspend; (d) intake converts times to UTC `Z`; (e) `Limits` > 0; (f) SSE tested over real HTTP (frames, ping, resume). Plus an automatic additive DB migration. | coordinator, budgets, schemas, db | `test_gaps.py`, `test_auth_errors.py` |
| Windows | ✅ `%-I`/`%-d` fixed; YAML and prompt files read as UTF-8 (the cause of 4 failing parser tests on Windows). | `context/values.py`, `domain.py`, `extract.py`, `verifier.py` | full suite green on Windows |

**Deviations from the plan**
- **The canonical seed stays at two providers.** Adding Coastal to the default story would make every run wait for a third reply and would change the demo script and 12 test modules. Coastal is a sandbox extra instead (`?extra=1`, intake picker, `GET /demo/providers`).
- **Offline mock mode can't find another option.** Its scripted snapshots can't re-coordinate, so rejecting there blocks with an honest "runs on the backend" question that offers only Stop. The backend path (`NEXT_PUBLIC_USE_MOCKS=0`) does re-coordinate.
- **Per-provider summaries are computed when the snapshot is built**, not stored as evidence. They are built only from facts, which already cite evidence.

**Limits that remain**
- **Photon live loop untested end to end (G1).** The live demo also needs `LIVE_USER_HANDLE` to text the line first.
- **Sign-in is a demo:** no password and user ids from display names. A real identity provider must replace `/auth/login` before any public use.
- **Mock mode:** only Stop for questions; three-provider and washer searches need the backend.
- **Services:** only appliance repair (dishwasher, washer) in `home_repair/v1`; other trades need new packs.
- **Answer limits:** "add provider" accepts custom handles, but in fixture mode only sandbox ids have scripted replies; a custom fixture provider will time out as "No reply".
- **Text approvals are off by default**; enabling them for the demo is a team decision (§6).

---

## 1. Current limits (as planned, before execution)

| Area | Limit today | Where | Impact |
|---|---|---|---|
| **Reject** | A rejected approval fails `request_approval` and the task goes **BLOCKED** with a `question.asked`. Orbit doesn't try the next eligible provider. | `core/coordinator.py` (`_request_approval`) | One "no" ends the run even when Bayside was eligible. |
| **Answering questions** | No endpoint resumes a BLOCKED task. The only exit is Cancel. | API (§3.6) | Every block is final in practice. |
| **Provider count** | The backend accepts N providers (`TaskCreate.providers` is a list; the planner and compare loop over it). Everything around it assumes two: `demo/seed.json`, `portal/providers.yaml`, the canned fixture replies, the presenter "Inject: Provider A" button, and the `grid-two` comparison layout. | seed, portal, `adapters/fixture_messaging.py`, `frontend/components/DemoPanel.tsx`, `TaskWorkspace.tsx` | A third provider has no portal page, no fixture reply and no room in the UI. |
| **Intake providers** | The intake form shows the seed's providers read-only. Custom providers are possible only through the JSON import. | `frontend/components/Intake.tsx` | Users can't add, remove or edit providers. |
| **Services** | One service, `dishwasher_repair`. The domain pack is `home_repair v1`, the quote parser looks for the word "dishwasher", and portal services are dishwasher-only. | `context/parser.py`, `context/packs/home_repair/v1.yaml`, `portal/providers.yaml` | Another appliance or trade isn't recognised and fails at extraction. |
| **Task list** | `GET /tasks` exists, but the UI has no screen for existing searches. | `frontend/app` | Users can't find or resume earlier searches. |
| **Sign-in** | None. A single implicit user; `approver` defaults to `"demo_user"`; CORS allows only `localhost:3000`. | API, UI | Not deployable beyond a local demo. |
| **Error shapes** | Four shapes: 422 `detail: [{loc,msg,type}]`, 409 approvals `detail: {code,current_hash,reason}`, 409 cancel / 404 `detail: "<text>"`, 502 portal `detail: "<text>"`. | `core/api/*` | The UI needs per-endpoint special cases. |
| **Case states** | `BLOCKED` covers budget, no eligible provider, rejection, verification FAIL / INSUFFICIENT, unknown booking and failed retries. The reason is free text in `status_reason`. | `TaskStatus`, coordinator | The UI can't show the right action for each kind of block. |
| **Photon (live)** | The adapter exists (Beta API: polling inbound, idempotent send, delivery receipts) but hasn't run on this machine (`photonhq-api` isn't installed). Shared-line rule: each provider must text the Orbit line first. Limit of 50 new conversations per line per day. The user is never messaged; summaries and reports exist only in the UI. | `adapters/photon.py`, `docs/integrations.md` | No real "Orbit texts you back" moment yet. |
| **Browser Use (live)** | Needs `browser-use` plus local Chromium. Not installed here. | `adapters/browser_use_adapter.py` | This machine runs fixture mode only. |
| **Platform** | Runs on Windows only with an **uncommitted** fix to `context/values.py` (`%-I` / `%-d` are glibc-only). Grammarly causes a dev-only hydration warning on `<body>`. | `context/values.py`, `frontend/app/layout.tsx` | Karthik should commit the fix; demo from an extension-free browser profile. |
| **Known core gaps** (from the Phase 4/5 audits) | (a) an older provider message can overwrite newer facts; (b) tick-level LLM extraction errors retry every second with no backoff or limit; (c) budgets are checked only at tick start, with a `>` off-by-one; (d) intake keeps non-UTC offsets; (e) `limits` aren't validated; (f) no HTTP-level SSE test. | core | None break the demo; fix before any real use. |

---

## 2. Priorities

| Priority | Work | Why now |
|---|---|---|
| **Now** (before freeze) | A. Reject → re-coordinate · B. Three providers in fixture · C. Provider gallery · G1. Photon live smoke | Visible in the demo, small, mostly inside existing contracts |
| **Next** | F. Error envelope, case states, answer endpoint · G2–G4. Photon summarize and report · core gaps (a)–(f) | Makes BLOCKED recoverable and live messaging trustworthy |
| **Later** | D. Services room and multi-service packs · E. Sign-in | Needs new packs, portal data and an identity decision |

---

## 3. Workstreams

### A. Reject → coordinate other options (Victor + Karthik + Adithya) — **Now**

**Goal.** Rejecting a proposal means "not this one", not "stop". Orbit moves to the next eligible provider and asks again. It never books without a fresh approval.

**Design.**
1. `POST /tasks/{id}/approvals` with `decision: "rejected"` records the decision as it does today.
2. The coordinator ingests the fact `{p}.declined_by_user = true`, with the approval id as its source, through `ingest_fact`. This is a new key (§5).
3. Karthik's `eligibility()` turns that fact into the reason `"declined by you"`, so `best_proposal()` skips the provider.
4. `request_approval` returns `skipped` with replan reason `"you declined <provider>"`. The planner adds compare → availability → approval for the next best provider and emits `provider.disqualified` and `plan.revised`.
5. If no eligible provider remains, the task goes BLOCKED with `question.asked` offering: raise the budget, widen the window, reconsider a declined provider, or stop. Answers arrive through F3.
6. Optional per-decision scope: `scope: "provider"` (default) or `"proposal"` (decline only this slot or price; the provider stays eligible if other slots exist).

**UI.** The Reject button becomes **"Not this one — find another"**, plus a secondary **"Stop here"** that cancels the task. The withdrawn card shows "Declined by you".

**Acceptance.**
- Reject Ace → approval requested for Bayside without passing through BLOCKED; the timeline shows `approval.decided (rejected)`, `provider.disqualified (declined by you)` and `plan.revised`.
- Reject both → BLOCKED with options; no portal submit ever happened.
- A stale hash still returns 409.

### B. More than two providers (Victor + Ansh + Adithya) — **Now (3 in fixture)**

**Backend.** No core change is needed: providers are a list, sends run in parallel, compare picks the best of N. Limits to keep:
- Intake caps providers at **10**, which fits the 40-tool-action default: about 1 send per provider, plus availability, booking and lookup for the chosen one.
- Live mode caps at the Photon line's daily new-conversation budget (50).

**Fixture and demo data.**
- Add `provider_c` to `demo/seed.json`, `portal/providers.yaml` and the fixture replies. Example: "Coastal Appliance Pros", $160, which is over budget and shows a third state.
- Presenter controls take a provider picker instead of the hard-coded "Provider A".

**Intake UI.** Editable provider rows (name, channel, handle, portal URL) with add and remove. The backend's 422 messages already cover duplicates, empty handles and fixture handles in live mode.

**Acceptance.** A three-provider fixture run reaches COMPLETED. The UI shows all three. `make test` covers N=3 in the planner and coordinator.

### C. Provider gallery — sliding, left to right (Adithya) — **Now**

**Goal.** Replace the two-column comparison with a horizontal gallery of every provider in the current sandbox run.

**Behavior.**
- **Order, left to right:** current proposal, then other eligible providers by charge, then disqualified or declined providers, then providers still awaiting a reply.
- **Each card shows:** name, a status chip (eligible / proposed / declined / over budget / no reply / awaiting), visit charge with superseded values struck through, fee scope, offered and portal slots, cancellation terms, an evidence link, and the **fixture** badge when the evidence is fixture.
- **Motion:** CSS scroll-snap track; prev/next buttons; ←/→ keys when focused; dots for position. It scrolls to the current proposal when the proposal changes, for example after a price-change replan. An optional slow auto-advance pauses on hover and focus and is off when `prefers-reduced-motion` is set.
- **Optional second strip:** evidence thumbnails such as portal screenshots once Browser Use runs live.

**Data.** `TaskView.providers`, `facts`, `eligibility` and `current_proposal` already carry everything. No backend change.

**Acceptance.** Works with 2 to 10 providers, at 400 px width, with keyboard only, and with reduced motion.

### D. Services room — searches beyond dishwasher repair (Karthik + Victor + Adithya + Ansh) — **Later**

**Goal.** One place to see and manage every search, for any supported service.

**Backend (Victor).**
- `GET /services` returns the catalog from the domain packs: `{id, label, pack, fields}`.
- `GET /tasks?service=&status=` filters existing searches.

**Context (Karthik).**
- Packs per service family: appliance repair (dishwasher, washer, dryer, fridge), then plumbing and HVAC.
- Move service detection from the `"dishwasher"` keyword in `parser.py` to each pack's synonyms.
- Fee rules per pack: diagnostic vs repair, trip charges.

**Portal (Ansh).** Services per provider in `providers.yaml`; booking forms list a provider's services.

**UI (Adithya).** A **Services** room with:
- a catalog grid;
- existing searches grouped by service and status (Needs approval / Waiting on providers / Blocked / Handled);
- "New search" prefilled from the chosen service;
- open, cancel or answer a blocked search.

**Acceptance.** A washer-repair fixture search runs end to end with its own pack and portal service. Dishwasher behavior is unchanged.

### E. Sign-in (room for it) — **Later**

**Today.** No identity; one implicit demo user.

**Now: leave seams.**
- A FastAPI dependency `current_user()` returns a fixed demo user, and every write endpoint takes it. That makes adding real auth one change.
- The approver comes from `current_user()`, not from the request body (§5).

**Later.**
- A managed identity provider (choice open: hosted auth vs our own OAuth), with session cookies.
- `Task.owner_id`; each user sees only their own tasks; approvals require the owner.
- SSE authorized by cookie; CORS set from env for the deployed origin.
- UI: sign-in page, signed-in header, sign-out. Mock mode stays usable without signing in.

### F. Errors and case states (Victor + Adithya) — **Next**

**F1. One error envelope.** Every non-2xx response:

```json
{"error": {"code": "stale_proposal", "message": "Terms changed since you saw them.",
           "retryable": false, "field": null, "details": {"current_hash": "…"}}}
```

422 keeps a `details.fields: [{loc, msg}]` list. During migration, existing `detail` bodies stay for one release.

**F2. Error codes**

| Code | HTTP | UI action |
|---|---|---|
| `invalid_intake` | 422 | Highlight fields |
| `stale_proposal` | 409 | Refresh the card ("Terms changed") |
| `already_terminal` | 409 | Show final state |
| `not_found` | 404 | Back to the Services room |
| `reset_disabled` | 403 | Hide the control |
| `portal_unreachable` | 502 | Retry; show integration status |
| `integration_blocked` | 503 | Explain the missing setup |
| `internal` | 500 | Generic message plus support id (Sentry event id) |

**F3. Case states and answers.**
- `Task.status` stays as is. Add a machine-readable reason code so the UI can offer the right actions.
- Add `POST /tasks/{id}/answers` with `{question_id, choice, params}` (§5). A valid answer applies the change (for example a new budget, which re-runs eligibility) and replans, moving BLOCKED → PLANNING → RUNNING.

| Reason code | Meaning | Offered actions |
|---|---|---|
| `awaiting_approval` | Proposal waiting | Approve · Find another · Stop |
| `waiting_on_providers` | Replies pending | Wait · Nudge (follow-up) |
| `no_eligible_provider` | All over budget, outside the window, or declined | Raise budget · Widen window · Reconsider · Stop |
| `user_rejected_all` | Every option declined | Reconsider · Add a provider · Stop |
| `verification_failed` | Confirmation ≠ approved terms | Contact provider · Stop |
| `verification_pending` | Evidence insufficient | Check again · Contact provider |
| `booking_unknown` | Booking outcome can't be confirmed | Check with provider (ref ORB-…) |
| `budget_exceeded` | Orbit's own action, LLM or runtime limits | Extend limits · Stop |
| `integration_blocked` | e.g. provider must text the Photon line first | Fix setup · Retry |
| `step_failed` | Retries exhausted | Retry · Stop |

**Acceptance.** Every BLOCKED path in the coordinator sets a code. Each code has UI copy and actions. Answering `no_eligible_provider` with a higher budget resumes and completes.

### G. Photon — really message, receive, summarize, report (Ansh + Karthik + Victor) — **G1 Now, G2–G4 Next**

**G1. Live smoke.**
- Install `photonhq-api`.
- Set `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`, `LIVE_PROVIDER_A/B_HANDLE` (consenting teammates only).
- Follow the shared-line procedure in `docs/integrations.md`: each provider texts the Orbit line first.
- Victor: the "must text first" send failure becomes `integration_blocked` (F3) instead of a retry loop.

**G2. Receive.** Already designed: polling inbound becomes an `InboundEvent(source="photon")` with dedup on the Photon message id. Add a test for out-of-order delivery, which ties into core gap (a).

**G3. Summarize.**
- Per-provider conversation summary (Karthik's LLM client, with provider text as untrusted input), stored as evidence and shown on each gallery card.
- A final task summary, which already exists, sent through G4.

**G4. Report to the user.**
- New optional `TaskCreate.user_contact` (§5).
- Orbit texts the user at key moments: an approval request with the exact terms and a short hash, "booked — verified", or "blocked — your options".
- **Approve by reply (later, gated):** accept `YES <hash8>` or `NO <hash8>` only from the task owner's handle, and only if the hash matches the current pending proposal. Anything else is ignored and logged. A provider's message can never approve.
- Reports follow the evidence standard: "handled" only after COMPLETED with a PASS verdict.

**Acceptance.** With two consenting teammates: a real inquiry, real replies, A's price change by text, the user gets an approval text, approves in the UI, receives a "booked — verified" text, and the summary matches the verifier's predicates.

---

## 4. Suggested order

| Slot | Items |
|---|---|
| Sat night | A (core + context + UI) · B with 3 providers in fixture · C gallery · G1 smoke |
| Sun morning, before 9:30 freeze | Commit the Windows fix · A/B/C tests green · demo script updated for "Find another" and three providers |
| After the hackathon | F, G2–G4, core gaps (a)–(f), then D, then E |

---

## 5. Contract changes to agree (Victor commits after agreement)

**Status: all nine are implemented on the working tree** (all additive with defaults; `detail` kept beside the new `error` envelope). Also added: `EvidenceKind` `user_decision`, `SendResult.error_code`, `TaskView.provider_summaries` / `open_question`, `GET /services`, `GET /demo/providers`, `/auth/me|login|logout`, timeline types `question.answered` / `report.sent`. Review before committing.

| # | Change | For | Owner of semantics |
|---|---|---|---|
| 1 | Fact key `{p}.declined_by_user: bool` (source = approval id) | A | Karthik |
| 2 | `ApprovalDecisionIn.scope: "provider" \| "proposal" = "provider"`, `reason: str \| None` | A | Victor |
| 3 | `POST /tasks/{id}/answers` `{question_id, choice, params}`; `question.asked` data gains `question_id` and `options[]`; new timeline type `question.answered` | F3 | Victor |
| 4 | Machine-readable reason code on `Task` (new field) and in `task.status_changed` data | F3 | Victor |
| 5 | Error envelope `{"error": {...}}` for all non-2xx responses | F1 | Victor |
| 6 | `GET /services`; `GET /tasks?service=&status=` | D | Victor |
| 7 | `Task.owner_id`; approver taken from the session, not the body | E | Victor |
| 8 | `TaskCreate.user_contact` (optional); timeline type `report.sent` | G4 | Victor / Ansh |
| 9 | `Limits` validation (> 0); intake normalizes timestamps to UTC `Z` | gaps (d)(e) | Victor |

---

## 6. Open questions

- **Reject scope:** should the default be "decline this provider" or "decline only this proposal"? Proposal: provider.
- **Provider cap:** 10 in fixture; what's realistic live given 50 new Photon conversations per line per day?
- **Second service for D:** washer repair (same pack family) or a different trade (plumbing)?
- **Identity choice for E**, and whether mock mode must keep working signed out.
- **Approve by text (G4):** in scope for the demo, or UI-only approvals until after the hackathon?
