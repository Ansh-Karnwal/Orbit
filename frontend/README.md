# Orbit frontend

Next.js App Router, strict TypeScript, Tailwind CSS, and a typed HTTP client for the shared backend contract. The offline story is runnable independently of the CP0 backend.

```sh
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. `.env.local` defaults to `NEXT_PUBLIC_USE_MOCKS=1`. The root `.env` is not automatically loaded by Next.js when it runs from `frontend/`.

- `NEXT_PUBLIC_USE_MOCKS=1`: browser-local fixture snapshots; no backend, messaging, LLM, browser-agent, or verifier execution. Automatic updates every three seconds, paused at approval cards. Use the price-change control at the Ace proposal. Only an explicit decision advances an approval.
- `NEXT_PUBLIC_USE_MOCKS=0`: real HTTP/SSE against `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`). No silent fallback to mocks. Restart/rebuild when changing public variables.
- Live intake requires `/health` to report live Photon and Browser Use integrations and the seed/import to provide non-fixture provider handles. The frontend does not invent handles or change the seed API.

The fixed offline scenario requires the next Tuesday 2–5 p.m. Los Angeles window, $150 visit budget, and canonical providers. Custom requests require the backend. Mock task state persists in the current tab's session storage. Reset opens a new mock task.

```sh
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
# Alternative when Chrome is already installed:
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

Dev/build use Webpack because Turbopack's PostCSS subprocess port was unavailable in this workspace. No external font download is required. The framework setup follows the [Next.js installation guide](https://nextjs.org/docs/app/getting-started/installation) and [Tailwind Next.js guide](https://tailwindcss.com/docs/installation/framework-guides/nextjs).

`lib/types.ts` mirrors `backend/app/core/schemas.py`. `lib/api.ts` exposes all task/demo/evidence endpoints; the Photon inbound webhook is intentionally not called by the frontend. `lib/useTaskStream.ts` handles snapshot reads, timeline merging, 250 ms refetch coalescing, reconnect backoff, and resume cursors. Approval requests always carry the displayed hash.

Keyboard shortcuts outside editable fields: **Shift+1** injects Ace's price change; **Shift+R** resets the demo. Controls are visible for fixture tasks or `?demo=1`. Backend reset clears shared demo state; use only with the team demo environment.

See [acceptance and hand-off](../docs/frontend_handoff.md), [CREAO checklist](../creao/README.md), and [demo script](../docs/demo_script.md).
