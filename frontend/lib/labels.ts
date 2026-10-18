import type { ReasonCode, TaskStatus } from "./types";

const SERVICE_LABELS: Record<string, string> = {
  dishwasher_repair: "Dishwasher repair",
  washer_repair: "Washing machine repair",
};

/** Human label for a service id (the backend's /services is the source of truth). */
export function serviceLabel(id: string): string {
  return (
    SERVICE_LABELS[id] ??
    id.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())
  );
}

/** What a BLOCKED (or any) task is waiting for, in plain words. */
export const REASON_LABELS: Record<ReasonCode, string> = {
  draft: "Draft",
  planning: "Building a plan",
  running: "Coordinating",
  awaiting_approval: "Needs your approval",
  waiting_on_providers: "Waiting on providers",
  verifying: "Verifying",
  completed: "Verified & complete",
  cancelled: "Cancelled",
  failed: "Failed",
  no_eligible_provider: "No option fits your limits",
  user_rejected_all: "You declined every option",
  verification_failed: "Booking doesn't match",
  verification_pending: "Verification pending",
  booking_unknown: "Booking state unknown",
  terms_changed_after_booking: "Terms changed after booking",
  budget_exceeded: "Paused at Orbit's limits",
  integration_blocked: "Setup needed",
  step_failed: "Needs your input",
};

export function statusLabel(
  status: TaskStatus,
  code: ReasonCode | null | undefined,
  fallback: string,
): string {
  if (status === "BLOCKED" && code && REASON_LABELS[code])
    return REASON_LABELS[code];
  return fallback;
}

/** Stable accent per provider position, so a third+ provider isn't colourless. */
const ACCENTS = ["accent-0", "accent-1", "accent-2", "accent-3", "accent-4"];
export function providerAccent(index: number): string {
  return ACCENTS[index % ACCENTS.length];
}
