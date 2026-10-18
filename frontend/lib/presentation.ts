import { isComplete } from "./format";
import { REASON_LABELS, serviceLabel } from "./labels";
import type { EvidenceKind, TaskStatus, TaskView } from "./types";

/** Human service name; known catalog services get their catalog label. */
export function serviceName(service: string): string {
  return serviceLabel(service);
}

export const statusLabels: Record<TaskStatus, string> = {
  DRAFT: "Getting started",
  PLANNING: "Building your plan",
  RUNNING: "Coordinating",
  AWAITING_APPROVAL: "Needs your approval",
  WAITING_EXTERNAL: "Waiting for providers",
  BLOCKED: "Needs attention",
  VERIFYING: "Checking your booking",
  COMPLETED: "Result ready",
  FAILED: "Verification failed",
  CANCELLED: "Coordination stopped",
};

export function taskLabel(view: TaskView): string {
  if (isComplete(view)) return "Verified & complete";
  if (view.task.status === "COMPLETED") return "Verification pending";
  // A blocked task says what it's waiting for (backend reason_code).
  const code = view.task.reason_code;
  if (view.task.status === "BLOCKED" && code && REASON_LABELS[code])
    return REASON_LABELS[code];
  return statusLabels[view.task.status];
}

// Typed by EvidenceKind so a new kind can't silently render without a title.
export const evidenceLabels: Record<EvidenceKind, string> = {
  message_in: "Provider message",
  message_out: "Outgoing message",
  portal_confirmation: "Portal record",
  browser_trace: "Booking activity",
  screenshot: "Screenshot",
  availability: "Available appointments",
  delivery_receipt: "Delivery receipt",
  creao_output: "Workflow import",
  user_decision: "Your decision",
};

export function evidenceProvider(view: TaskView, id: string): string {
  const item = view.evidence.find((e) => e.id === id);
  const providerId =
    item?.extracted.provider_id ??
    view.facts.find((f) => f.source_id === id)?.key.split(".")[0];
  return view.providers.find((p) => p.id === providerId)?.name ?? "Orbit";
}
