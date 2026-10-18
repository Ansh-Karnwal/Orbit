import type {
  Approval,
  ApprovalDecisionIn,
  DemoInjectIn,
  DemoInjectResult,
  DemoResetIn,
  DemoResetResult,
  EvidenceArtifact,
  Health,
  PortalFaultIn,
  Task,
  TaskCreate,
  TaskView,
} from "./types";
import { ApiError, StaleProposalError } from "./errors";
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
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = response.statusText;
    }
    if (
      response.status === 409 &&
      detail &&
      typeof detail === "object" &&
      "code" in detail &&
      detail.code === "stale_proposal"
    ) {
      const d = detail as { current_hash?: string; reason?: string };
      throw new StaleProposalError(
        d.current_hash ?? null,
        d.reason ?? "Terms changed",
      );
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
const mocks = async () => (await import("@/mocks/store")).mock;
const taskPath = (id: string) => `/tasks/${encodeURIComponent(id)}`;
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
  seed: async (): Promise<TaskCreate> =>
    USE_MOCKS ? (await mocks()).seed() : request("/demo/seed"),
  create: async (body: TaskCreate): Promise<TaskView> =>
    USE_MOCKS ? (await mocks()).create(body) : request("/tasks", body),
  list: async (): Promise<Task[]> =>
    USE_MOCKS ? (await mocks()).list() : request("/tasks"),
  task: async (id: string, signal?: AbortSignal): Promise<TaskView> =>
    USE_MOCKS
      ? (await mocks()).get(id)
      : request(taskPath(id), undefined, signal),
  approve: async (id: string, body: ApprovalDecisionIn): Promise<Approval> =>
    USE_MOCKS
      ? (await mocks()).approve(id, body)
      : request(`${taskPath(id)}/approvals`, body),
  cancel: async (id: string): Promise<Task> =>
    USE_MOCKS
      ? (await mocks()).cancel(id)
      : request(`${taskPath(id)}/cancel`, {}),
  evidence: async (id: string): Promise<EvidenceArtifact[]> =>
    USE_MOCKS
      ? (await mocks()).get(id).evidence
      : request(`${taskPath(id)}/evidence`),
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
    const r = await fetch(api.artifactUrl(id));
    if (!r.ok) throw new ApiError(r.status, "Artifact unavailable");
    return r.blob();
  },
  eventsUrl: (id: string, seq: number) =>
    `${API_BASE}${taskPath(id)}/events?after_seq=${seq}`,
};
