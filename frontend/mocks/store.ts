import type {
  AnswerIn,
  ApprovalDecisionIn,
  DemoInjectIn,
  PortalFaultIn,
  ProviderSpec,
  TaskCreate,
  TaskView,
  UserInfo,
} from "@/lib/types";
import { ApiError, StaleProposalError } from "@/lib/errors";
import { buildStory, demoSeed } from "./scenario";
type Run = {
  snapshots: TaskView[];
  index: number;
  fault: PortalFaultIn["mode"];
  seen: string[];
  extras: TaskView["timeline"];
  stopped: boolean;
};
const runs = new Map<string, Run>();
const listeners = new Map<string, Set<() => void>>();
function persist(id: string) {
  if (typeof sessionStorage !== "undefined")
    sessionStorage.setItem(`orbit:${id}`, JSON.stringify(runs.get(id)));
}
function run(id: string): Run {
  if (!runs.has(id)) {
    const saved =
      typeof sessionStorage !== "undefined"
        ? sessionStorage.getItem(`orbit:${id}`)
        : null;
    if (saved) runs.set(id, JSON.parse(saved));
    else if (id === "tsk_demo")
      runs.set(id, {
        snapshots: buildStory(),
        index: 0,
        fault: "none",
        seen: [],
        extras: [],
        stopped: false,
      });
    else throw new ApiError(404, "Mock task not found. Start a new task.");
  }
  return runs.get(id)!;
}
function notify(id: string) {
  persist(id);
  listeners.get(id)?.forEach((f) => f());
}
function extra(id: string, type: string, message: string) {
  const r = run(id);
  r.extras.push({
    id: `tl_extra_${r.extras.length}`,
    task_id: id,
    seq: 1000 + r.extras.length,
    type,
    message,
    data: {},
    at: new Date().toISOString(),
  });
}
// Not "orbit:<id>": list() treats every "orbit:" sessionStorage key as a mock task id.
const USER_KEY = "orbit-user";
const DEMO_USER: UserInfo = {
  user_id: "demo_user",
  display_name: "Demo user",
  authenticated: false,
  auth_mode: "demo",
};
export const mock = {
  seed: demoSeed,
  sandboxProviders(): ProviderSpec[] {
    return [
      ...demoSeed().providers,
      {
        id: "provider_c",
        name: "Coastal Appliance Pros",
        channel: "fixture",
        handle: "fixture:provider_c",
        portal_url: "http://localhost:8100/p/provider_c",
      },
    ];
  },
  me(): UserInfo {
    if (typeof sessionStorage === "undefined") return DEMO_USER;
    const saved = sessionStorage.getItem(USER_KEY);
    return saved ? (JSON.parse(saved) as UserInfo) : DEMO_USER;
  },
  login(display_name: string): UserInfo {
    // Tab-local only: the offline mock has no server to hold a session.
    const user: UserInfo = {
      user_id: `u_${display_name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      display_name: display_name.trim(),
      authenticated: true,
      auth_mode: "demo",
    };
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  },
  logout(): UserInfo {
    sessionStorage.removeItem(USER_KEY);
    return DEMO_USER;
  },
  answer(id: string, body: AnswerIn) {
    if (body.choice !== "stop")
      throw new ApiError(
        409,
        "The offline mock can only stop here. Run with the backend (NEXT_PUBLIC_USE_MOCKS=0) to let Orbit look for other options.",
      );
    return mock.cancel(id);
  },
  get(id: string): TaskView {
    const r = run(id);
    const v = structuredClone(r.snapshots[r.index]);
    v.timeline = [...v.timeline, ...r.extras];
    return v;
  },
  list() {
    if (typeof sessionStorage !== "undefined") {
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key?.startsWith("orbit:")) run(key.slice(6));
      }
    }
    return [...runs.keys()].map((id) => mock.get(id).task);
  },
  create(input: TaskCreate) {
    // Scripted prices/times are meaningful only for the canonical scenario.
    const seed = demoSeed();
    if (
      input.mode !== "fixture" ||
      input.constraints.service !== "dishwasher_repair" ||
      input.constraints.max_visit_charge_cents !== 15000 ||
      input.constraints.window_start !== seed.constraints.window_start ||
      input.constraints.window_end !== seed.constraints.window_end ||
      input.providers.map((p) => p.id).join() !== "provider_a,provider_b"
    )
      throw new ApiError(422, [
        {
          loc: ["body", "constraints"],
          msg: "Offline story requires the seeded dishwasher scenario, next Tuesday 2–5 p.m., and $150 budget. Use the backend for custom scenarios.",
        },
      ]);
    const id = `tsk_mock_${crypto.randomUUID().slice(0, 8)}`;
    runs.set(id, {
      snapshots: buildStory(input, id),
      index: 0,
      fault: "none",
      seen: [],
      extras: [],
      stopped: false,
    });
    persist(id);
    return mock.get(id);
  },
  tick(id: string) {
    const r = run(id);
    if (r.stopped || [2, 4, 6].includes(r.index)) return;
    r.index++;
    if (r.index === 6) mock.applyFault(id);
    notify(id);
  },
  subscribe(id: string, cb: () => void) {
    const set = listeners.get(id) ?? new Set();
    set.add(cb);
    listeners.set(id, set);
    const timer = setInterval(() => mock.tick(id), 3000);
    return () => {
      clearInterval(timer);
      set.delete(cb);
    };
  },
  approve(id: string, body: ApprovalDecisionIn) {
    const r = run(id);
    const v = r.snapshots[r.index];
    const approval = v.approvals.at(-1);
    if (
      !approval ||
      approval.status !== "requested" ||
      approval.proposal_hash !== body.proposal_hash
    )
      throw new StaleProposalError(
        approval?.proposal_hash ?? null,
        "Proposal has changed",
      );
    approval.status = body.decision;
    approval.approver = body.approver;
    approval.decided_at = new Date().toISOString();
    if (body.decision === "rejected") {
      // The scripted story can't re-coordinate (the backend does): it offers the
      // workspace's revise-or-stop recovery instead of faking another option.
      r.stopped = true;
      v.task.status = "BLOCKED";
      v.task.reason_code = "user_rejected_all";
      v.task.status_reason =
        "You declined this proposal. Revise it as a new request or stop coordination here.";
      v.current_proposal = null;
    } else if (r.index === 4) r.index = 5;
    else {
      r.index = 3;
    }
    notify(id);
    return structuredClone(approval);
  },
  inject(body: DemoInjectIn) {
    const r = run(body.task_id);
    const ext = body.external_id ?? crypto.randomUUID();
    if (r.seen.includes(ext)) {
      extra(
        body.task_id,
        "message.duplicate_ignored",
        "Duplicate provider message ignored.",
      );
      notify(body.task_id);
      return { inbound_id: `inb_${ext}`, created: false };
    }
    if (r.index !== 2)
      throw new ApiError(
        409,
        "Wait for the Ace proposal before injecting the price change.",
      );
    r.seen.push(ext);
    r.index = 3;
    notify(body.task_id);
    return { inbound_id: `inb_${ext}`, created: true };
  },
  fault(mode: PortalFaultIn["mode"]) {
    for (const [id, r] of runs) {
      r.fault = mode;
      persist(id);
    }
    return { mode };
  },
  cancel(id: string) {
    const r = run(id);
    const view = r.snapshots[r.index];
    if (["COMPLETED", "FAILED", "CANCELLED"].includes(view.task.status))
      throw new ApiError(409, "This request has already ended.");
    view.approvals
      .filter((a) => a.status === "requested")
      .forEach((a) => {
        a.status = "invalidated";
        a.invalidated_reason = "Coordination stopped.";
      });
    r.stopped = true;
    r.snapshots[r.index].task.status = "CANCELLED";
    notify(id);
    return mock.get(id).task;
  },
  applyFault(id: string) {
    const r = run(id);
    const v = r.snapshots[6];
    if (r.fault === "none") return;
    if (r.fault === "timeout_after_submit") {
      extra(
        id,
        "booking.ambiguous",
        "Submission timed out; checking for an existing booking.",
      );
      extra(
        id,
        "booking.reconciled",
        "Existing fixture booking located by Orbit reference. No duplicate submission.",
      );
      return;
    }
    const missing = ["no_confirmation", "down"].includes(r.fault);
    v.task.status = missing ? "BLOCKED" : "FAILED";
    v.task.summary = null;
    v.verification = {
      ...v.verification!,
      verdict: missing ? "INSUFFICIENT_EVIDENCE" : "FAIL",
      explanation: missing
        ? "No portal evidence available. Task remains incomplete."
        : "Portal visit charge differs from the approved $145.00.",
      predicates: [
        {
          name: "Portal terms match approval",
          passed: missing ? null : false,
          detail: missing
            ? "Required portal evidence is missing."
            : "Portal charge is $190.00; approval is $145.00.",
          evidence_ids: missing ? [] : ["evd_portal"],
        },
      ],
    };
    v.timeline = v.timeline.filter(
      (e) => e.type !== "task.completed" && e.type !== "verification.completed",
    );
    if (missing)
      v.evidence = v.evidence.filter((e) => e.kind !== "portal_confirmation");
    else
      v.evidence = v.evidence.map((e) =>
        e.kind === "portal_confirmation"
          ? {
              ...e,
              claim_level: "booking_request_submitted",
              extracted: { ...e.extracted, visit_charge_cents: 19000 },
            }
          : e,
      );
    v.steps
      .filter((s) => s.plan_version === 2 && s.kind === "summarize")
      .forEach((s) => (s.state = "blocked"));
    extra(id, "verification.completed", v.verification.explanation);
  },
};
