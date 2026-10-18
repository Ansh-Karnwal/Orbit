# Orbit — 3:00 demo recording script

Record the fixture fallback early. Keep the fixture banner and integration chips visible. This checkout can record the offline UI story; do not narrate its snapshots as live Photon, Browser Use, CREAO, or an executing verifier.

| Time | Screen and action | Narration |
| --- | --- | --- |
| 0:00–0:20 | Intake hero | “Arranging a repair means chasing replies, comparing fees, and checking what actually happened. Orbit only says handled when evidence supports it.” |
| 0:20–0:40 | Show Tuesday 2–5 p.m., $150 visit cap, and approval rule. Start task. | “These are my boundaries. I approve the exact terms before a booking request.” If using executed CREAO output, show its real connected record and disclose a manual hand-off. Otherwise use manual intake. |
| 0:40–1:10 | Provider cards and source drawer | “Quotes become versioned facts with sources.” For offline mode say “These providers and browser outcomes are simulated.” Only show a consenting teammate's phone and name Photon when the integration is actually live. |
| 1:10–1:50 | Ace approval → Shift+1 → $120 struck to $190; invalidated approval; plan v2 | “Ace looked cheapest. A $70 trip charge breaks the budget. The old permission no longer applies. Both prices remain in the record, and the plan moves to Bayside.” Optionally click duplicate message and point to deduplication. |
| 1:50–2:30 | Bayside $145 proposal; time and cancellation terms; explicit Approve | “I am approving this provider, this slot, this diagnostic charge, and these cancellation terms.” In a live take, show the real browser run on `/p/provider_b`. In the fallback, identify the result as simulated. |
| 2:30–2:50 | Verification checklist → PASS → final summary | “Completion depends on the result matching the approved terms. This covers diagnosis including travel. Parts and labor are still unknown.” Offline take: “The mock illustrates the verification gate; actual verifier execution is a separate integration check.” |
| 2:50–3:00 | Cut to a separately recorded mismatch run with FAIL | “If the evidence disagrees, the task stays incomplete.” Close with the product name. |

## Recording setup

- Run `NEXT_PUBLIC_USE_MOCKS=1 npm run dev` in `frontend/` for the offline fallback; open `http://localhost:3000`.
- Use a 1440×900 or similar desktop window with readable zoom. Close unrelated tabs and redact private handles.
- The story advances every three seconds, pausing at approvals. Use the deliberate pause at Ace to explain the terms before injecting.
- **Shift+1:** inject the price change. **Shift+R:** reset. Shortcuts are ignored in editable fields.
- For the failure cut, reset and select `mismatch` in Presenter controls before approving Bayside. Capture FAIL and absence of the final summary. Do not try to fit a second full run into ten seconds.
- `no_confirmation`: insufficient evidence. `timeout_after_submit`: ambiguous submission followed by reconciliation. These are scripted in offline mode; repeat against the backend to demonstrate real behavior.
- Capture a backup take early, then a live take after integration checks pass. Save the final public URL and duration below after upload.

Recording status: **not recorded or uploaded in this hand-off**.

Final video URL: **pending**. Target duration: **3:00**. Confirm actual contest video requirements with organizers.
