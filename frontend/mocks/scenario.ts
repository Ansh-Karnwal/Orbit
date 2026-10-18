import type {
  Approval,
  ContextFact,
  EvidenceArtifact,
  PlanStep,
  Proposal,
  TaskCreate,
  TaskView,
  TimelineEvent,
} from "@/lib/types";
import { mockProposalHash } from "./hash";
import { localInput, localToUtc } from "@/lib/format";
export const PRICE_CHANGE =
  "Sorry, I forgot — there's a $70 trip charge on top, so $190 total.";
export function demoSeed(now = new Date()): TaskCreate {
  const tz = "America/Los_Angeles";
  const day = new Date(
    `${localInput(now.toISOString(), tz).slice(0, 10)}T12:00:00Z`,
  );
  day.setUTCDate(day.getUTCDate() + ((2 - day.getUTCDay() + 7) % 7 || 7));
  const date = day.toISOString().slice(0, 10);
  return {
    outcome_text:
      "Arrange a dishwasher repair visit on Tuesday between 2 and 5 p.m., with a total visit charge of at most $150. Confirm the diagnostic fee and cancellation terms. Ask me before committing to a booking.",
    constraints: {
      service: "dishwasher_repair",
      window_start: localToUtc(`${date}T14:00`, tz),
      window_end: localToUtc(`${date}T17:00`, tz),
      timezone: tz,
      max_visit_charge_cents: 15000,
      require_diagnostic_fee_confirmed: true,
      require_cancellation_terms: true,
      approval_policy: "before_booking",
    },
    providers: [
      {
        id: "provider_a",
        name: "Ace Appliance Repair",
        channel: "fixture",
        handle: "fixture:provider_a",
        portal_url: "http://localhost:8100/p/provider_a",
      },
      {
        id: "provider_b",
        name: "Bayside Appliance Service",
        channel: "fixture",
        handle: "fixture:provider_b",
        portal_url: "http://localhost:8100/p/provider_b",
      },
    ],
    limits: {
      max_tool_actions: 40,
      max_runtime_s: 1800,
      max_llm_calls: 60,
      reply_timeout_s: 600,
    },
    mode: "fixture",
    source: "demo_seed",
    creao_ref: null,
  };
}
export function buildStory(
  intake: TaskCreate = demoSeed(),
  id = "tsk_demo",
): TaskView[] {
  const now = new Date().toISOString();
  const at = (mins: number) =>
    new Date(
      Date.parse(intake.constraints.window_start) + mins * 60_000,
    ).toISOString();
  const aSlot = { start: at(60), end: at(120) },
    bSlot = { start: at(30), end: at(90) };
  const events: TimelineEvent[] = [];
  const emit = (
    type: string,
    message: string,
    data: Record<string, unknown> = {},
  ) => {
    events.push({
      id: `tl_${events.length + 1}`,
      task_id: id,
      seq: events.length + 1,
      type,
      message,
      data,
      at: new Date(Date.parse(now) + events.length * 1000).toISOString(),
    });
  };
  const evidence = (key: string, text: string): EvidenceArtifact => ({
    id: `evd_${key}`,
    task_id: id,
    kind: "message_in",
    source: "fixture_messaging",
    uri: null,
    mime_type: "text/plain",
    sha256: null,
    extracted: { text },
    claim_level: null,
    is_fixture: true,
    provider_ref: null,
    captured_at: now,
  });
  const msgA = evidence(
    "a1",
    "Hi! Dishwasher repair visit is $120. I can do Tuesday 3–4pm. Free cancellation with 24 hours notice.",
  );
  const msgB = evidence(
    "b1",
    "Yes we repair dishwashers. Diagnostic visit is $145 including travel. Tuesday 2:30–3:30pm or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours. Parts and labor are quoted after diagnosis.",
  );
  const msgChange = evidence("a2", PRICE_CHANGE);
  const fact = (
    p: string,
    key: string,
    value: unknown,
    source: string,
    version = 1,
  ): ContextFact => ({
    id: `fct_${p}_${key}_${version}`,
    task_id: id,
    key: `${p}.${key}`,
    value,
    currency: key.endsWith("cents") ? "USD" : null,
    scope: key === "visit_charge_cents" ? "diagnostic_visit" : null,
    source_id: source,
    observed_at: now,
    valid_until: null,
    status: "confirmed",
    version,
    supersedes: null,
  });
  const facts: ContextFact[] = [];
  for (const [p, charge, slot, source, terms, scope] of [
    [
      "provider_a",
      12000,
      aSlot,
      msgA.id,
      "Free cancellation with 24 hours notice.",
      "diagnostic_visit",
    ],
    [
      "provider_b",
      14500,
      bSlot,
      msgB.id,
      "Cancel free more than 12 hours ahead; $25 inside 12 hours.",
      "diagnostic_visit_including_travel",
    ],
  ] as const) {
    facts.push(
      ...[
        fact(p, "visit_charge_cents", charge, source),
        fact(p, "service_supported", true, source),
        fact(p, "fee_scope", scope, source),
        fact(
          p,
          "slots_offered",
          p === "provider_b"
            ? [slot, { start: at(120), end: at(180) }]
            : [slot],
          source,
        ),
        fact(p, "cancellation_terms", terms, source),
        fact(p, "repair_cost_known", false, source),
      ],
    );
  }
  const proposal = (
    p: string,
    charge: number,
    slot: typeof aSlot,
  ): Proposal => ({
    task_id: id,
    provider_id: p,
    provider_name: intake.providers.find((x) => x.id === p)?.name ?? p,
    service: intake.constraints.service,
    slot_start: slot.start.replace(".000Z", "Z"),
    slot_end: slot.end.replace(".000Z", "Z"),
    visit_charge_cents: charge,
    fee_scope:
      p === "provider_b"
        ? "diagnostic_visit_including_travel"
        : "diagnostic_visit",
    cancellation_terms: String(
      facts.find((f) => f.key === `${p}.cancellation_terms`)?.value,
    ),
    repair_cost_known: false,
    terms_version: 1,
    source_fact_ids: facts
      .filter((f) => f.key.startsWith(p + "."))
      .map((f) => f.id),
  });
  const approval = (p: Proposal, key: string): Approval => ({
    id: `apr_${key}`,
    task_id: id,
    proposal: p,
    proposal_hash: mockProposalHash(p),
    status: "requested",
    approver: null,
    requested_at: now,
    decided_at: null,
    expires_at: null,
    invalidated_reason: null,
  });
  const a = approval(proposal("provider_a", 12000, aSlot), "a"),
    b = approval(proposal("provider_b", 14500, bSlot), "b");
  const kinds: PlanStep["kind"][] = [
    "send_inquiry",
    "await_reply",
    "extract_quote",
    "compare_quotes",
    "read_availability",
    "request_approval",
    "submit_booking",
    "verify",
    "summarize",
  ];
  const steps = kinds.map((kind, i): PlanStep => ({
    id: `stp_1_${i}`,
    task_id: id,
    kind,
    provider_id: i >= 4 ? "provider_a" : null,
    depends_on: i ? [`stp_1_${i - 1}`] : [],
    state: i === 0 ? "succeeded" : "pending",
    attempts: i === 0 ? 1 : 0,
    max_attempts: 3,
    idempotency_key: `${id}:1:${i}`,
    not_before: null,
    result: null,
    error: null,
    plan_version: 1,
    created_at: now,
    updated_at: now,
  }));
  emit("task.created", "Repair coordination started.");
  emit("message.sent", "Inquiries submitted to two providers.");
  const view: TaskView = {
    task: {
      id,
      outcome_text: intake.outcome_text,
      constraints: intake.constraints,
      limits: intake.limits,
      mode: "fixture",
      status: "WAITING_EXTERNAL",
      status_reason: "Waiting for provider replies",
      source: intake.source,
      creao_ref: intake.creao_ref,
      summary: null,
      created_at: now,
      updated_at: now,
    },
    providers: intake.providers,
    facts: [],
    eligibility: {
      provider_a: ["Awaiting quote"],
      provider_b: ["Awaiting quote"],
    },
    steps,
    approvals: [],
    current_proposal: null,
    evidence: [],
    verification: null,
    timeline: [],
    integrations: {
      photon: "fixture",
      browser_use: "fixture",
      creao: intake.source === "creao" ? "manual-handoff" : "not-used",
      llm: "fixture",
    },
  };
  const snapshots: TaskView[] = [];
  const snap = () => {
    view.task.status_reason =
      view.task.status === "WAITING_EXTERNAL"
        ? "Waiting for provider replies"
        : "";
    view.timeline = structuredClone(events);
    snapshots.push(structuredClone(view));
  };
  snap();
  view.facts = facts;
  view.evidence = [msgA, msgB];
  view.eligibility = { provider_a: [], provider_b: [] };
  view.task.status = "RUNNING";
  view.steps.forEach((s, i) => {
    s.state = i < 4 ? "succeeded" : "pending";
  });
  emit("message.received", "Both provider quotes received.");
  emit(
    "fact.added",
    "Visit charges and cancellation terms extracted with sources.",
  );
  snap();
  const availableA: EvidenceArtifact = {
    ...evidence("availability_a", ""),
    kind: "availability",
    source: "fixture_browser",
    claim_level: "slot_offered",
    extracted: { slots: [aSlot] },
  };
  view.evidence.push(availableA);
  view.facts.push(fact("provider_a", "portal_slots", [aSlot], availableA.id));
  a.proposal.source_fact_ids.push("fct_provider_a_portal_slots_1");
  a.proposal_hash = mockProposalHash(a.proposal);
  view.task.status = "AWAITING_APPROVAL";
  view.approvals = [a];
  view.current_proposal = a.proposal;
  view.steps[4].state = "succeeded";
  view.steps[5].state = "succeeded";
  emit("approval.requested", "Review Ace Appliance Repair at $120.00.", {
    approval_id: a.id,
  });
  snap();
  view.facts = view.facts.map((f) =>
    f.key === "provider_a.visit_charge_cents"
      ? { ...f, status: "superseded" }
      : f,
  );
  const change = fact(
    "provider_a",
    "visit_charge_cents",
    19000,
    msgChange.id,
    2,
  );
  change.supersedes = "fct_provider_a_visit_charge_cents_1";
  view.facts.push(change);
  view.evidence.push(msgChange);
  view.eligibility.provider_a = ["Over budget: $190.00 > $150.00"];
  view.approvals = [
    {
      ...a,
      status: "invalidated",
      invalidated_reason: "Visit charge changed $120.00 → $190.00.",
    },
  ];
  view.current_proposal = null;
  view.task.status = "RUNNING";
  view.steps.forEach((s, i) => {
    if (i >= 6) s.state = "skipped";
  });
  emit("message.received", "Ace adds a $70.00 trip charge.", {
    evidence_id: msgChange.id,
  });
  emit("fact.superseded", "Visit charge v1 → v2: $120.00 → $190.00.", {
    old_value: 12000,
    new_value: 19000,
    fact_id: change.id,
  });
  emit("conflict.detected", "Ace exceeds the $150.00 visit budget.", {
    provider_id: "provider_a",
    kind: "budget_violation",
  });
  emit(
    "approval.invalidated",
    "Previous approval withdrawn because the price changed.",
    { approval_id: a.id },
  );
  emit("plan.revised", "Plan revised (v2): Provider A over budget.", {
    plan_version: 2,
    reason: "Provider A over budget",
    added_step_ids: ["stp_2_4", "stp_2_5", "stp_2_6", "stp_2_7", "stp_2_8"],
    skipped_step_ids: ["stp_1_6", "stp_1_7", "stp_1_8"],
  });
  snap();
  view.steps.push(
    ...steps.slice(4).map((s, i) => ({
      ...s,
      id: `stp_2_${i + 4}`,
      idempotency_key: `${id}:2:${i + 4}`,
      provider_id: "provider_b",
      plan_version: 2,
      state: i < 2 ? ("succeeded" as const) : ("pending" as const),
      depends_on: i ? [`stp_2_${i + 3}`] : ["stp_1_3"],
    })),
  );
  const availableB: EvidenceArtifact = {
    ...evidence("availability_b", ""),
    kind: "availability",
    source: "fixture_browser",
    claim_level: "slot_offered",
    extracted: { slots: [bSlot] },
  };
  view.evidence.push(availableB);
  view.facts.push(fact("provider_b", "portal_slots", [bSlot], availableB.id));
  b.proposal.source_fact_ids.push("fct_provider_b_portal_slots_1");
  b.proposal_hash = mockProposalHash(b.proposal);
  view.approvals.push(b);
  view.current_proposal = b.proposal;
  view.task.status = "AWAITING_APPROVAL";
  emit("availability.read", "Bayside has a matching portal slot.");
  emit("approval.requested", "Review Bayside Appliance Service at $145.00.", {
    approval_id: b.id,
  });
  snap();
  view.approvals[1] = {
    ...b,
    status: "approved",
    approver: "demo_user",
    decided_at: now,
  };
  view.task.status = "VERIFYING";
  view.current_proposal = null;
  view.steps
    .filter((s) => s.plan_version === 2)
    .forEach((s, i) => {
      s.state = i < 3 ? "succeeded" : i === 3 ? "running" : "pending";
    });
  emit("approval.decided", "Exact Bayside terms approved.", {
    approval_id: b.id,
  });
  emit(
    "booking.submitted",
    "Booking request submitted. Independent verification pending.",
  );
  snap();
  view.task.status = "COMPLETED";
  view.task.summary =
    "Bayside Appliance Service: $145.00 for the diagnostic visit including travel. Parts and labor are unknown until diagnosis. Cancellation is free more than 12 hours ahead; $25 inside 12 hours.";
  const confirmation: EvidenceArtifact = {
    ...evidence("portal", ""),
    kind: "portal_confirmation",
    source: "fixture_browser",
    claim_level: "booking_verified",
    extracted: {
      confirmation_id: "BK-MOCK-145",
      provider_id: "provider_b",
      service: intake.constraints.service,
      slot_start: bSlot.start,
      slot_end: bSlot.end,
      visit_charge_cents: 14500,
      cancellation_terms: b.proposal.cancellation_terms,
      orbit_ref: `${id}:2:6`,
    },
  };
  view.evidence.push(confirmation);
  view.verification = {
    id: "ver_mock",
    task_id: id,
    approval_id: b.id,
    verdict: "PASS",
    explanation:
      "Illustrative mock predicates match the approved terms. No real booking took place.",
    created_at: now,
    predicates: [
      "Provider matches approval",
      "Service matches request",
      "Slot fits requested window",
      "Visit charge matches approval and budget",
      "Cancellation terms match",
      "Approval matches current terms",
      "Portal evidence exists",
    ].map((name) => ({
      name,
      passed: true,
      detail: "Matches the approved fixture proposal.",
      evidence_ids: [confirmation.id],
    })),
  };
  view.steps
    .filter((s) => s.plan_version === 2)
    .forEach((s) => {
      s.state = "succeeded";
    });
  emit(
    "verification.completed",
    "Booking verified in the offline mock story.",
    { verification_id: "ver_mock" },
  );
  emit("task.completed", "Fixture story complete.");
  snap();
  return snapshots;
}
