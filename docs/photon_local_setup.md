# Local Photon setup

The root `.env` contains the locally supplied credentials and two consenting provider handles. It is gitignored with owner-only permissions. `MESSAGING_MODE=photon` selects the existing live adapter; the browser frontend's offline mock switch is independent.

A local `.venv` contains the core backend and `photonhq-api==0.5.0`. Check authentication, assignments, and inbound reply routes without sending messages:

```sh
PYTHONPATH=backend .venv/bin/python backend/scripts/check_photon.py
```

Each test recipient has their own shared-line assignment. The check prints the assigned Orbit number beside a masked recipient. Each recipient must send a blue iMessage from their configured phone number to that assigned line before Orbit can reply. SMS or an Apple ID email sender does not establish a route for the configured phone number.

Run offline adapter checks:

```sh
cd backend
../.venv/bin/python -m pytest tests/adapters/test_photon_mapping.py -q
```

Do not interpret successful authentication or a `live` health label as proof of delivery. Confirm inbound routing and a `delivered` status on a real message. Browser Use and the end-to-end live booking flow need separate verification. The current frontend mock mode does not contact Photon.

## Running the integrated local session

The local frontend configuration now uses `NEXT_PUBLIC_USE_MOCKS=0`; the root configuration selects live Photon and Browser Use. Context extraction currently uses the deterministic parser (`LLM_MODE=fixture`), not an Anthropic call. Messaging is real; the provider website remains the local demo portal.

From the repository root, use separate terminals:

```sh
(cd portal && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8100)
(cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000)
(cd frontend && npm run dev)
```

The live session uses `backend/orbit-live.db`, separate from the default fixture database. Do not start duplicate servers if these ports are already in use. Booking still requires approving the proposal in the UI. The single-provider test uses Bayside's portal identity with the consenting first phone as its messaging handle.

## OpenAI message drafting and extraction

Install `backend/requirements/context.txt`, then configure the gitignored root `.env`:

```dotenv
LLM_MODE=live
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
OPENAI_API_KEY=your-local-key
```

Restart the backend after changing these settings. OpenAI uses the Responses API with typed structured outputs and `store=False`. In live mode it drafts inquiries/follow-ups and extracts provider quote fields. Fixture tasks keep deterministic message templates. Browser Use continues to use its own `bu-2-0` model.

Drafts contain questions only; exact time, budget, and approval policy are appended by code. Drafting failures block sending. Requests contain task requirements and provider quote text, but no messaging handles or API keys in prompts. Quote extraction retains its existing conservative parser fallback. Booking and verification remain controlled by the application.

`message.drafted` timeline events record the drafting provider/model. Already-sent inquiries are not rewritten or resent after switching models. A task already awaiting approval stays there.
