import type {
  AnswerIn,
  Approval,
  ApprovalDecisionIn,
  DemoInjectIn,
  DemoInjectResult,
  DemoResetIn,
  DemoResetResult,
  EvidenceArtifact,
  Health,
  PortalFaultIn,
  ProviderSpec,
  ServiceInfo,
  Task,
  TaskCreate,
  TaskStatus,
  TaskView,
  UserInfo,
} from "./types";
import { ApiError, ErrorBody, StaleProposalError } from "./errors";
export { ApiError, StaleProposalError } from "./errors";
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";
export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"
).replace(/\/$/, "");
export async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    cache: "no-store",
    credentials: "include", // the sign-in cookie (demo sign-in today)
  });
  if (!response.ok) {
    let payload: { detail?: unknown; error?: ErrorBody } | undefined;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    const error = payload?.error ?? null;
    const detail = payload?.detail ?? response.statusText;
    const legacy =
      detail && typeof detail === "object" && "code" in detail
        ? (detail as { code?: string; current_hash?: string; reason?: string })
        : null;
    if (
      response.status === 409 &&
      (error?.code === "stale_proposal" || legacy?.code === "stale_proposal")
    ) {
      throw new StaleProposalError(
        (error?.details?.current_hash as string | undefined) ??
          legacy?.current_hash ??
          null,
        (error?.details?.reason as string | undefined) ??
          legacy?.reason ??
          "Terms changed",
      );
    }
    throw new ApiError(response.status, detail, error);
  }
  return response.json() as Promise<T>;
}
const mocks = async () => (await import("@/mocks/store")).mock;
const taskPath = (id: string) => `/tasks/${encodeURIComponent(id)}`;
const query = (params: Record<string, string | boolean | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== false && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};
export const MOCK_SERVICES: ServiceInfo[] = [
  {
    id: "dishwasher_repair",
    label: "Dishwasher repair",
    pack: "home_repair/v1",
    description:
      "Diagnostic visit for a dishwasher that won't drain, clean or start.",
  },
  {
    id: "washer_repair",
    label: "Washing machine repair",
    pack: "home_repair/v1",
    description:
      "Diagnostic visit for a washing machine that won't spin, drain or start.",
  },
];
export const api = {
  health: async (): Promise<Health> =>
    USE_MOCKS
      ? {
          ok: true,
          mode: "fixture",
          integrations: {
            photon: "fixture",
            browser_use: "fixture",
            creao: "manual-handoff",
            llm: "fixture",
          },
        }
      : request("/health"),
  seed: async (
    opts: { service?: string; extra?: boolean } = {},
  ): Promise<TaskCreate> =>
    USE_MOCKS
      ? (await mocks()).seed()
      : request(`/demo/seed${query(opts)}`),
  sandboxProviders: async (): Promise<ProviderSpec[]> =>
    USE_MOCKS
      ? (await mocks()).sandboxProviders()
      : request("/demo/providers"),
  services: async (): Promise<ServiceInfo[]> =>
    USE_MOCKS ? MOCK_SERVICES : request("/services"),
  create: async (body: TaskCreate): Promise<TaskView> =>
    USE_MOCKS ? (await mocks()).create(body) : request("/tasks", body),
  list: async (
    filter: { service?: string; status?: TaskStatus } = {},
  ): Promise<Task[]> =>
    USE_MOCKS
      ? (await mocks())
          .list()
          .filter(
            (t: Task) =>
              (!filter.service || t.constraints.service === filter.service) &&
              (!filter.status || t.status === filter.status),
          )
      : request(`/tasks${query(filter)}`),
  task: async (id: string, signal?: AbortSignal): Promise<TaskView> =>
    USE_MOCKS
      ? (await mocks()).get(id)
      : request(taskPath(id), undefined, signal),
  approve: async (id: string, body: ApprovalDecisionIn): Promise<Approval> =>
    USE_MOCKS
      ? (await mocks()).approve(id, body)
      : request(`${taskPath(id)}/approvals`, body),
  answer: async (id: string, body: AnswerIn): Promise<Task> =>
    USE_MOCKS
      ? (await mocks()).answer(id, body)
      : request(`${taskPath(id)}/answers`, body),
  cancel: async (id: string): Promise<Task> =>
    USE_MOCKS
      ? (await mocks()).cancel(id)
      : request(`${taskPath(id)}/cancel`, {}),
  evidence: async (id: string): Promise<EvidenceArtifact[]> =>
    USE_MOCKS
      ? (await mocks()).get(id).evidence
      : request(`${taskPath(id)}/evidence`),
  me: async (): Promise<UserInfo> =>
    USE_MOCKS ? (await mocks()).me() : request("/auth/me"),
  login: async (display_name: string): Promise<UserInfo> =>
    USE_MOCKS
      ? (await mocks()).login(display_name)
      : request("/auth/login", { display_name }),
  logout: async (): Promise<UserInfo> =>
    USE_MOCKS ? (await mocks()).logout() : request("/auth/logout", {}),
  reset: async (body: DemoResetIn): Promise<DemoResetResult> =>
    USE_MOCKS
      ? {
          task_id: body.create_task
            ? (await mocks()).create((await mocks()).seed()).task.id
            : null,
        }
      : request("/demo/reset", body),
  inject: async (body: DemoInjectIn): Promise<DemoInjectResult> =>
    USE_MOCKS
      ? (await mocks()).inject(body)
      : request("/demo/inject-event", body),
  fault: async (body: PortalFaultIn): Promise<PortalFaultIn> =>
    USE_MOCKS
      ? (await mocks()).fault(body.mode)
      : request("/demo/portal-fault", body),
  artifactUrl: (id: string) =>
    `${API_BASE}/artifacts/${encodeURIComponent(id)}`,
  artifact: async (id: string): Promise<Blob> => {
    const r = await fetch(api.artifactUrl(id), { credentials: "include" });
    if (!r.ok) throw new ApiError(r.status, "Artifact unavailable");
    return r.blob();
  },
  eventsUrl: (id: string, seq: number) =>
    `${API_BASE}${taskPath(id)}/events?after_seq=${seq}`,
};
