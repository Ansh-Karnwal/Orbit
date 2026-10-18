import { isComplete } from "./format";
import type { TaskStatus, TaskView } from "./types";

export function serviceName(service: string): string {
  const label = service.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
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
  return isComplete(view)
    ? "Verified & complete"
    : view.task.status === "COMPLETED"
      ? "Verification pending"
      : statusLabels[view.task.status];
}

export const evidenceLabels: Record<string, string> = {
  message_in: "Provider message",
  message_out: "Outgoing message",
  portal_confirmation: "Portal record",
  browser_trace: "Booking activity",
  screenshot: "Screenshot",
  availability: "Available appointments",
  delivery_receipt: "Delivery receipt",
  creao_output: "Workflow import",
};

export function evidenceProvider(view: TaskView, id: string): string {
  const item = view.evidence.find((e) => e.id === id);
  const providerId =
    item?.extracted.provider_id ??
    view.facts.find((f) => f.source_id === id)?.key.split(".")[0];
  return view.providers.find((p) => p.id === providerId)?.name ?? "Orbit";
}
