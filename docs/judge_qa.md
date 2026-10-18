# Judge Q&A

**Why not just a chatbot?**
The product makes task state, sources, approval, and completion criteria inspectable. A changed price invalidates an exact proposal rather than merely changing a conversational answer. The offline UI demonstrates this interaction; the real durability guarantees require the backend integration.

**How is the verifier independent?**
The team contract gives it a read-only evidence interface and deterministic predicates, returning PASS, FAIL, or INSUFFICIENT_EVIDENCE. The coordinator cannot override the verdict. Show Karthik's actual implementation/tests when integrated; the frontend's synthetic predicates are not proof of independence.

**What if the provider lies?**
Evidence proves what a provider or portal reported, not that the repair will happen or be good. Orbit can check consistency with approved terms and flag missing/conflicting evidence. It must not represent a diagnostic quote as a final repair price.

**What's real versus simulated?**
The frontend, JSON validation, approval interaction, and evidence display are real code. With mocks enabled, provider replies, booking evidence, and verifier outcomes are scripted locally. Backend mode reports subsystem status and per-artifact fixture tags. In this checkout, backend routes remain CP0 stubs; live sponsor execution is not yet validated.

**Can the agent approve for me?**
The UI never auto-approves. It submits the exact displayed hash after the user clicks. The server must reject stale terms and enforce approval again at execution time; the client alone cannot enforce that boundary.

**What if the price changes after I approve?**
The contract requires invalidation and replanning. The UI retains the invalidated card and its reason. A stale approval submission returns HTTP 409 and prompts review of the new terms.

**What happens if the browser times out after submitting?**
The intended coordinator reconciles with the existing booking using an idempotency reference before retrying. The offline demo illustrates this; use the actual portal fault test to substantiate the no-duplicate guarantee.

**Is the $145 the repair price?**
No. It is the diagnostic visit including travel. Parts and labor remain unknown until diagnosis. The approval and final summary say so.

**How does it extend to other domains?**
The intended domain-pack boundary supplies fact keys, rules, and required evidence for a new domain. Each new workflow also needs appropriate adapters, explicit approval scope, and independent completion predicates. That is planned extensibility, not a claim of current multi-domain support.

**What does CREAO contribute?**
The planned workflow turns a request into validated intake and creates a connected coordination record. Today there is a checklist, synthetic sample, and manual JSON import. Only claim executed CREAO use after capturing the workflow, connected output, and run history.

**What about prompt injection?**
Provider messages and webpages are untrusted data and cannot change user constraints or approval rules. The UI renders them as text rather than HTML. The backend must enforce the same boundary during extraction and execution.

**What would you validate next?**
The real-backend vertical slice; changed terms during approval; reconnect/replay; duplicate inbound messages; missing and mismatched portal evidence; and ambiguous submission recovery. Then collect inspectable live integration runs.
