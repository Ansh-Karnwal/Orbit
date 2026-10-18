# Orbit integrations: Photon, Browser Use, provider portal

Owner: Ansh. This is the source of truth for how Orbit talks to the outside world, what is real versus fixture, and the evidence for the sponsor-eligibility claims. Facts were checked against official docs on 2026-10-17. Doc copies are in the session scratchpad; the URLs are cited below.

## Summary

| Integration | Product used | Version | Language | Mode switch |
|---|---|---|---|---|
| Messaging | **Photon Beta API** (`photonhq-api`), iMessage on a shared line | `photonhq-api==0.5.0` | Python, no sidecar | `MESSAGING_MODE=photon` |
| Browser automation | **Browser Use open-source library** (local Chromium) | `browser-use==0.13.11` | Python | `BROWSER_MODE=browser_use` |
| Booking site | Orbit mock provider portal (`portal/`) | n/a | FastAPI + Jinja | always local, :8100 |
| Offline fallbacks | `fixture_messaging`, `fixture_browser` | n/a | Python | default (`fixture`) |

The Python venv is 3.12 (`uv venv --python 3.12 .venv`). Both SDKs also install on 3.14. Installing `browser-use` downgrades `websockets` to 15.x, which uvicorn handles fine.

## Env vars

The core `Settings` already has `MESSAGING_MODE`, `PHOTON_API_KEY`, `LIVE_PROVIDER_A_HANDLE`, `LIVE_PROVIDER_B_HANDLE`, `BROWSER_MODE`, `BROWSER_USE_API_KEY`, `ANTHROPIC_API_KEY` and `PORTAL_BASE_URL`.

Victor, please add these to `.env.example`. They are read by `app/adapters/settings.py`:

```
PHOTON_PROJECT_ID=                  # Beta project id, pho_prj_…
PHOTON_AGENT_HANDLE=                # shared line number assigned to the project (display only)
PHOTON_POLL_S=2                     # inbound + delivery-status polling interval
BROWSER_USE_HEADLESS=0              # 0 = visible Chromium (better for the live demo)
BROWSER_USE_LLM=auto                # auto | browser_use | anthropic
BROWSER_USE_MODEL=                  # empty = library default (ChatBrowserUse bu-2-0)
BROWSER_USE_MAX_STEPS=25
BROWSER_USE_TIMEOUT_S=120
```

`PHOTON_BRIDGE_URL` can be dropped, because the Beta API doesn't need a Node sidecar.

Portal-only env vars are `PORTAL_DB_PATH` (default `portal/portal.db`), `PORTAL_TIMEOUT_DELAY_S` (default 90) and `PORTAL_CATALOGUE` (default `providers.yaml`; `providers.live.yaml` for the one-text live script).

## Photon

### What we use and why
Photon runs two separate platforms (https://photon.codes/docs/skill.md):
- **Stable ("Spectrum")** is a TypeScript-only SDK (`spectrum-ts` 12.11.0). It has no public HTTP send endpoint (https://photon.codes/docs/webhooks/quickstart), so using it from Python would need a Node sidecar.
- **Beta (v2)** is a REST API with an official Python client, `photonhq-api` (https://photon.codes/docs/beta/get-started/imessage). **We use Beta.**

If the event gives out Stable credentials instead, the registry reports `photon: blocked: …doesn't look like a Beta project…`. The fallback plan is a `photon-bridge/` Node sidecar on `spectrum-ts`.

### How the adapter works (`backend/app/adapters/photon.py`)
- **Send:** `POST /v1/projects/{id}/messages` with `{spaceId, senderId, content:{type:"text",format:"plain",text}}` and an `idempotency-key: orbit:<step key>` header. Photon returns 202 with a `pho_msg_…` id and `status`.
  - Evidence: `message_out` at `MESSAGE_SUBMITTED`, with `provider_ref` set to the Photon message id.
  - Retrying with the same key is safe because Photon deduplicates on that header.
- **Receive:** a background task polls `GET /v1/projects/{id}/messages?direction=received&createdSince=…` every `PHOTON_POLL_S`, using a 10 s overlap because the API is eventually consistent.
  - Each text from a configured provider handle becomes `InboundEvent(source="photon", external_id=<pho_msg id>)`.
  - Messages from other senders are dropped and not logged.
- **Delivery status:** ids we sent are polled with `direction=sent`. Status `delivered` saves `delivery_receipt` evidence at `MESSAGE_DELIVERED`. The possible statuses are `received | dispatched | accepted | delivered | failed`.
- **No webhook.** Beta webhook signature verification isn't documented (the secret is `whsec_…`, but neither the headers nor the algorithm are), so `photon_routes.router = None`.
- **Safety:**
  - Only handles in `LIVE_PROVIDER_A/B_HANDLE` are messaged; any other recipient is refused.
  - Handles are normalized to E.164 and masked in logs (`+1•••••0101`).
  - Message bodies are never logged.

### ⚠️ Shared-line rule (changes the live demo script)
A shared iMessage line can't send the first message. It only sends "in direct Spaces, only to a peer with an active Assignment who has messaged it since that Assignment" (the `send_message` docstring in `photonhq-api`; https://photon.codes/docs/beta/get-started/imessage).

**Live demo procedure:**
1. In the Photon Beta dashboard, add each teammate-provider's number as an iMessage assignment.
2. **Before creating the task**, each teammate texts the Orbit line once, for example "Hi, this is Ace Appliance Repair".
3. Create the live task. Orbit learns `(spaceId, agent user id)` from that first text and can now send the inquiry.

If a provider hasn't texted first, `send()` returns `failed` with `shared iMessage line can't send first: provider +1•••••0101 must text the Orbit line once, then retry`. **Victor:** surface that error as BLOCKED rather than retrying in a loop.

### One-text live script (Ace gets booked)
Start the portal with `PORTAL_CATALOGUE=providers.live.yaml`. In that price list Ace's $120 includes travel and has no extra fee, and Bayside costs $185. Each teammate sends **one** text, exactly as written below, after the inquiry arrives. The verifier compares the cancellation wording with the portal word for word.

- **Ace (provider A):** `Hi! Dishwasher diagnostic visit is $120 including travel. Tuesday 3–4pm. Free cancellation with 24 hours notice.`
- **Bayside (provider B):** `Yes we repair dishwashers. Diagnostic visit is $185 including travel. Tuesday 2:30–3:30pm or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours. Parts and labor are quoted after diagnosis.`

Bayside goes over the $150 budget, so Orbit proposes Ace. Browser Use books Ace's 3–4pm slot, and the review page matches the approved $120. The fixture story (Ace's hidden $70 trip charge) still uses `providers.yaml`.

### Limits
- 5 req/s per project on the management API (https://photon.codes/docs/api-reference/rate-limit).
- 50 new conversations per line per day (https://photon.codes/docs/spectrum-ts/providers/imessage/connection-and-routing).
- Beta publishes no numeric limits, though responses carry `RateLimit` headers.

## Browser Use

### What we use and why
We use the **open-source `browser-use` library** with a local Chromium. Browser Use Cloud can't reach `localhost` without a tunnel (https://github.com/browser-use/browser-use/blob/main/skills/qa/SKILL.md), and Cloud V4 has no navigation allow-list.

The open-source library gives us:
- `Browser(allowed_domains=[portal host])`
- post-run page HTML and screenshots through `keep_alive=True`
- a GIF and conversation log of each run

**LLM:** `ChatBrowserUse()` (the sponsor key `BROWSER_USE_API_KEY`) is preferred. Otherwise it uses `ChatAnthropic(model=BROWSER_USE_MODEL)` with `ANTHROPIC_API_KEY`.

**Setup:** `uvx browser-use install` installs Chromium. A Playwright Chromium is already cached on Ansh's machine.

### How the adapter works (`backend/app/adapters/browser_use_adapter.py`)
- **`read_availability`:** the agent opens `/p/{pid}/book?date=…` and reports the slots.
  - The slots Orbit actually uses come from the page's `data-slot-start/end` attributes; the agent's text is kept only as an advisory note.
  - Evidence: a screenshot, `availability` at `SLOT_OFFERED`, and a `browser_trace` (GIF plus metadata).
  - One retry.
- **`submit_booking`** runs in two phases:
  - **A.** The agent fills the form from the `BookingRequest` only (slot value, service, name, contact, reference = `orbit_ref`). It stops on the review page and must not click Confirm.
    - Orbit then checks the review page against the approved proposal: service, slot_start, visit_charge_cents and reference.
    - Any mismatch returns `failed` and nothing is booked, because the portal only records a booking on Confirm.
    - The agent is told to report UNAVAILABLE if the exact slot is gone. Page text is treated as untrusted.
  - **B.** Orbit clicks `#confirm-booking` itself, through Browser Use's CDP page actor, and parses the result:
    - Confirmation page → `confirmed`.
    - "Request received" page → `submitted_unconfirmed`.
    - `slot_unavailable` error page → `failed`.
    - Timeout or crash after the click → `ambiguous`.
  - **Never retried.** The coordinator reconciles through `find_booking`.
  - Evidence: before/after screenshots, `portal_confirmation` at `BOOKING_REQUEST_SUBMITTED` with the confirmation page HTML attached, and a `browser_trace`.
- **`find_booking`:** deterministic navigation to `/p/{pid}/lookup?ref=…` in the Browser Use browser, with no LLM call. A failed lookup returns `ambiguous`, never `None`, so a failure can't trigger a duplicate booking.
- **Domain restriction:** the browser is created with `allowed_domains=[host]`, and Orbit also checks after the run that every visited URL was on the portal host.
- **Session ref:** `browser-use-oss:<run id>`. The open-source library has no cloud session id; the GIF and the conversation folder (`ARTIFACT_DIR/_browser_use/<run id>/`) are the trace.

## Provider portal (`portal/`)
- **Run:** `cd portal && ../.venv/bin/python -m uvicorn main:app --port 8100`.
- **Providers** (`portal/providers.yaml`):
  - Ace: $120 visit, with "Trip charge: $70" listed only under Fees.
  - Bayside: $145 diagnostic visit including travel, and the note "Parts and labor quoted after diagnosis".
- **Slots:** the next 14 weekdays in `America/Los_Angeles`, computed per date so they stay correct across the change from daylight to standard time. A booked slot disappears.
- **Routes:** HTML pages (`/`, `/p/{pid}`, `/book`, `/review`, `/book` POST, `/lookup`), a JSON API (`/api/p/{pid}/slots|book|bookings`), and admin endpoints (`/admin/fault|reset|state`).
- **Fault modes** change what the response shows, never the stored record, so lookup always returns the truth:

| Mode | Behaviour |
|---|---|
| `timeout_after_submit` | Records the booking, then sleeps `delay_s` (default 90) before responding. |
| `mismatch` | Records the real booking; the confirmation shows the slot +3 h and a $165.00 charge. |
| `no_confirmation` | Records the booking; the page says "We received your request…" with no id. |
| `down` | 503 on booking POSTs only; slots and lookup still work. |

- **No dedup:** the portal does not deduplicate by reference, so reconciliation has to look before resubmitting.
- **Safety:** no payment fields anywhere, and the footer says "Demo portal for LA Hacks — not a real business".

## Real vs fixture

| Artifact | Fixture mode | Live mode |
|---|---|---|
| Outbound message | `fixture_messaging`, `is_fixture=True`; nothing is sent | Photon `pho_msg_…` id, `is_fixture=False` |
| Provider replies | Scripted from `demo/fixture_script.json` (`fx:{task}:{pid}:{n}`) | Real iMessage from a consenting teammate |
| Delivery receipt | none (send returns `delivered` labelled as fixture) | Photon status `delivered`, `MESSAGE_DELIVERED` |
| Availability | Portal JSON API over HTTP, no browser, no screenshots | Browser Use agent run plus deterministic DOM parse, with screenshot |
| Booking | Portal JSON API `POST /api/p/{pid}/book` | Browser Use fills the form; Orbit confirms on the real HTML page |
| Trace | none | `browser_trace` GIF, conversation log, step and URL list |

The registry (`integration_status()`) reports `live` only when a live adapter actually initialized. Otherwise it reports `fixture`, or `blocked: <reason>`. A live task never falls back to a fixture silently.

## Sponsor evidence log
Fill in one row per live run (Ansh). Redact handles to `+1•••••1234`.

| When (PT) | Task id | Photon message ids | Browser Use session ref | Screenshots / trace | Notes |
|---|---|---|---|---|---|
| 2026-10-17 16:06 | `tsk_live` (adapter smoke test) | n/a | read: `browser-use-oss:bu_bf878b62618d4055`; book: `browser-use-oss:bu_674e833fb020482b` | `ARTIFACT_DIR/_browser_use/<run id>/run.gif` + `conversation/` (local) | `browser-use==0.13.11`, `ChatBrowserUse` (bu-2-0). The agent read Bayside's slots and filled the form (3 steps), and Orbit confirmed on the review page. Portal confirmation `BK-M0NZ`, ref `ORB-live1019`, Mon 2026-10-19 2:30–3:30 PM PT, $145.00. `find_booking` matched it, and the portal held exactly 1 booking. |
| 2026-10-17 15:57 | `tsk_live` | n/a | `bu_b12394e9a81c4dde`, `bu_dbf7c29dbf8e49fb` | gif only | Free-tier key: the LLM gateway refused the agent. The adapter failed safely and booked nothing. |

## Open questions for sponsor reps
1. **Photon:** are the LA Hacks credentials Stable (Spectrum) or Beta? Is the line shared or dedicated? Can a dedicated line send the first message?
2. **Photon:** is there an active challenge at this event, and does messaging alone qualify? What submission evidence is needed? (Research found no Photon challenge listed for this event. Photon advertises doubling the prize for winners who use its SDK, https://photon.codes/weekly-update/april-17-2026; unconfirmed for this event.)
3. **Photon Beta:** what are the webhook signature header and algorithm, the rate-limit numbers, and is there a Python Socket.IO client?
4. **Browser Use:** does the open-source library qualify, or is Cloud required? Are there hackathon credits for `ChatBrowserUse`? How should judges access traces (we provide the GIF, conversation log and screenshots)?

## Tests
- `make test` (with `PY=.venv/bin/python`) runs `backend/tests/adapters`: fixture adapters against the real portal app in-process, the parser, the registry, handles, Photon mapping and the Browser Use helpers.
- `cd portal && ../.venv/bin/python -m pytest tests` runs the portal tests; `make test` doesn't reach them.
- Live smoke tests are skipped unless `RUN_LIVE=1`: `tests/adapters/test_live_browser_use.py` (needs the portal running and an LLM key) and `tests/adapters/test_live_photon.py` (needs Photon Beta credentials and a teammate).
