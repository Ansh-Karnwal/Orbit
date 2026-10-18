# Orbit — submission draft

**Readiness note:** This draft describes the product and distinguishes implemented UI from intended backend behavior. Before publishing, replace the status paragraph with evidence from the integrated build. No sponsor eligibility, video link, or live integration is claimed here.

## Inspiration

The hard part of arranging a repair is often the work between messages: checking fees, comparing times, noticing a changed quote, and following through. A polished answer is not the same as a finished task. We wanted a system that could show both its decisions and the evidence behind its result.

## What it does

Orbit coordinates a dishwasher diagnostic visit within a user's time window and budget. Its demo exposes a realistic complication: the cheapest provider adds a $70 trip charge, taking a $120 visit to $190. Orbit's workspace preserves both fact versions, withdraws the old approval, and shows a revised plan for a $145 alternative. The user approves exact terms, and the final summary is gated on a passing verification result. It explicitly distinguishes the diagnostic visit from unknown parts and labor.

Orbit applies AI to the administrative work between a request and a confirmed outcome. It coordinates service providers using domain-specific context, adapts when constraints change, and independently verifies the result before marking the task complete.

## How we built it

The frontend uses Next.js App Router, strict TypeScript, Tailwind, a typed HTTP client, and a resumable event stream. The team architecture separates versioned context, durable coordination, and read-only verification. Photon messaging and Browser Use portal automation are the intended adapters. CREAO is planned for structured intake plus a meaningful connected record-creation action; the current UI supports manually importing its JSON output.

**Current verified scope:** the frontend runs with labelled offline fixtures. Those snapshots simulate messages, booking evidence, and verifier outcomes. The backend in this checkout is a CP0 skeleton; real adapter and verifier behavior is not established by the frontend demo. CREAO has a checklist and synthetic sample, not execution evidence. We will only claim integrations that we can demonstrate and inspect.

## Challenges

A price change invalidates more than a comparison table: it invalidates permission tied to the previous terms. We made that boundary visible with retained approvals, source links, and exact proposal hashes. We also separated submission claims from completion claims and made fixture labelling persistent even when a nominally live task contains fixture evidence.

## Accomplishments

We built an intake-to-outcome UI that makes uncertainty inspectable: versioned quotes, eligibility reasons, exact-term approval, revised plans, evidence viewers, and predicate-level verification. The offline story includes duplicate messages, conflicting portal evidence, missing evidence, and ambiguous submission recovery as clearly labelled illustrations.

## What we learned

Approval and evidence belong in the product model from the start. Otherwise, a conversational interface can make an action sound more certain than it is. A small domain-specific workflow makes those boundaries easier to test and explain.

## What's next

Integrate and validate the team's backend, collect real Photon and Browser Use execution evidence, execute the CREAO connected workflow, and test the failure paths against the real portal. Then extend the domain-pack approach to other bounded administrative tasks with explicit constraints and completion predicates.

## Judging dimensions

| Dimension | Demonstration / proof to show |
| --- | --- |
| Technical Depth | Fact versions and provenance; hash-bound approvals; actual backend reconciliation and read-only verifier tests once integrated |
| Product Thinking & Impact | User budget and appointment constraints survive changed provider terms; unknown repair costs remain explicit |
| Execution & Polish | Responsive task workspace, clear action states, accessible controls, honest fixture banner, recorded fallback |
| Originality & Insight | Treat completion as an evidence-backed claim, separate from an agent's narrative |

## Disclosure and publication checklist

Planning briefs were prepared before the event. Implementation and any reused tooling must be disclosed according to the organizers' actual rules. Confirm the authorized coding window before representing eligibility.

- [ ] Reconcile integration claims with Ansh's `docs/integrations.md` and actual recordings.
- [ ] Link public repository, working demo, and a recorded video; check access without signing in.
- [ ] Include CREAO only after the workflow, connected action, and run history are inspectable; otherwise retain the explicit “planned” disclosure.
- [ ] Verify category and sponsor requirements with the organizers.
- [ ] Replace this readiness note with an accurate final build status.
- [ ] Submit manually by the organizer-confirmed deadline; internal target in the brief is Sunday 11:00 a.m. Pacific.
