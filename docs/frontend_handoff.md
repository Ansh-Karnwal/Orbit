# Frontend acceptance and team hand-off

Implemented files are confined to `frontend/`, `creao/`, `docs/` (excluding team/integration ownership), and root `README.md`. Shared backend models and routes are unchanged.

## Acceptance map

| Requirement | Visible UI / proof | Status and remaining validation |
| --- | --- | --- |
| A14 fixture honesty | Persistent banner from task mode, any fixture evidence, or any fixture integration; integration chips; artifact tags; offline control label | Implemented and component-tested; validate mixed-mode backend responses at integration |
| A15 inspectable CREAO use | Import panel sets `source=creao`, preserves reference, and labels manual hand-off; execution checklist in `creao/` | Platform workflow, connected action, real run output, and screenshots remain unexecuted. No sponsor-use claim |
| A3 replan visibility | Provider A's $120 history, $190 active price, budget reason, plan v2 and timeline divider | Offline story implemented; actual conflict/replan logic belongs to backend |
| A6 exact approval | Provider, slot and timezone, diagnostic charge/scope, cancellation, unknown repair costs, short hash; buttons submit displayed full hash | Client test covers request binding; backend must enforce atomic validation |
| A7 invalidation | Retained grey withdrawn card; reason; stale HTTP 409 refreshes with “Terms changed” | Client and mock tested; exercise concurrent live price change against backend |
| A8–A10 failure visibility | FAIL / insufficient evidence panels, absent completion summary; ambiguous/reconciled timeline events | Offline paths implemented; real mismatch/missing/reconcile tests pending teammates' backend/portal |
| A11 supporting moment | Duplicate ignored event via repeated external ID | Mock demonstrates display; real inbound deduplication pending integration |

The brief groups A8–A10 without individually defining their IDs. This mapping preserves that grouping instead of inventing exact criterion definitions.

## Run and environment

```sh
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

- `NEXT_PUBLIC_USE_MOCKS=1`: explicit offline fixture story. Set `0` for the real backend.
- `NEXT_PUBLIC_API_BASE=http://localhost:8000`: backend base for fetch, SSE, and artifacts.
- Restart/rebuild when changing either value. Root `.env` is not automatically a frontend env file.
- Presenter controls: Shift+1 injects the fee; Shift+R resets; editable fields suppress shortcuts.
- Playwright: install Chromium, or set `PLAYWRIGHT_CHANNEL=chrome` for installed Chrome.

## Integration checklist for Victor / Karthik / Ansh

- [ ] Replace CP0 route bodies. The frontend expects the exact §3.6 responses and named SSE `timeline` events.
- [ ] Verify `TaskView` includes all fact versions, providers, approvals, evidence, and runtime integration status.
- [ ] Verify SSE replay after `after_seq`, duplicate/reordered delivery, and server restart.
- [ ] Verify HTTP 422 error `loc` paths and 409 `stale_proposal` response.
- [ ] Configure the backend seed with consenting live handles before expecting the Live toggle to enable.
- [ ] Verify changed terms invalidate approval before booking and no UI path can bypass server-side enforcement.
- [ ] Verify `/artifacts/{id}` files and source references, including inbound-event sources without separate artifacts.
- [ ] Run real mismatch, no-confirmation, timeout/reconciliation, duplicate-message, and mixed-fixture scenarios.
- [ ] Reconcile README integration claims with Ansh's integration evidence.
- [ ] Run frontend checks plus root `make test` before merging. `make test` currently excludes frontend checks.

## Suggested small commits

1. `[web] scaffold app, contract types, API, resumable stream and offline story`
2. `[web] add validated intake and CREAO JSON import`
3. `[web] show fact versions, bound approvals, evidence and verification`
4. `[web] add presenter controls and regression coverage`
5. `[creao] document executable intake workflow and honest manual hand-off`
6. `[docs] add architecture, submission draft, demo script and judge Q&A`

No commits, merge, live messages, real booking, CREAO execution, video upload, or Devpost submission are performed by this hand-off. The sample JSON is synthetic and must not be presented as execution evidence.

## Validation recorded in this hand-off

- `npm run lint`: passed with no warnings.
- `npm run typecheck`: passed.
- `NEXT_PUBLIC_USE_MOCKS=1 npm run build`: passed with Webpack after the browser server stopped.
- `npm test`: 28 tests passed, including formatting/DST, import validation, approval binding/staleness, fixture triggers, completion gating, failure mocks, and SSE resume/cleanup.
- `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`: 4 tests passed (full story and mismatch, desktop and 390px phone); screenshots inspected.
- `make test PY=/private/tmp/orbit-backend-check/bin/python`: all 5 existing backend smoke tests passed. A temporary virtual environment supplied dependencies; backend files were not changed. One upstream Starlette/httpx deprecation warning remains.
- All seven mock TaskView snapshots and the CREAO sample parsed successfully through the actual Pydantic contract; every mock proposal hash matched Python's `compute_hash()`.

The initial Turbopack build was blocked by its subprocess port requirement. Webpack builds successfully. Do not run dev/browser tests and production build concurrently: they write generated Next.js types. These checks establish frontend and CP0 compatibility, not a working backend vertical slice or live sponsor execution.
