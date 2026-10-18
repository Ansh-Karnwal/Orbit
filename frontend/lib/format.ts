import type { ClaimLevel, TaskView, Verdict } from "./types";
export function money(cents: number): string {
  if (!Number.isSafeInteger(cents))
    throw new Error("Money must be integer cents");
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
}
export function localTime(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));
}
export function localTimestamp(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));
}
export function localRange(start: string, end: string, tz: string): string {
  const day = (iso: string) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      weekday: "short",
      month: "short",
      day: "numeric",
    }).format(new Date(iso));
  return day(start) === day(end)
    ? `${day(start)} · ${localTime(start, tz)}–${localTime(end, tz)}`
    : `${day(start)} · ${localTime(start, tz)} – ${day(end)} · ${localTime(end, tz)}`;
}
export function claimLabel(
  claim: ClaimLevel | null,
  verdict?: Verdict,
): string {
  const labels = {
    message_submitted: "Message submitted",
    message_delivered: "Message delivered",
    slot_offered: "Slot offered",
    booking_request_submitted: "Booking request submitted",
    booking_verified:
      verdict === "PASS" ? "Booking verified" : "Verification pending",
  };
  return claim ? labels[claim] : "Evidence captured";
}
export function hasFixtures(view: TaskView): boolean {
  return (
    view.task.mode === "fixture" ||
    view.evidence.some((e) => e.is_fixture) ||
    Object.values(view.integrations).some((s) =>
      s.toLowerCase().includes("fixture"),
    )
  );
}
export function isComplete(view: TaskView): boolean {
  return (
    view.task.status === "COMPLETED" && view.verification?.verdict === "PASS"
  );
}
/** Preserve provider text as data, while keeping premature completion language out of the UI. */
export function safeWording(text: string, verdict?: Verdict): string {
  return verdict === "PASS"
    ? text
    : text
        .replace(/\bhandled\b/gi, "in progress")
        .replace(/\bbooked\b/gi, "booking requested")
        .replace(/\bconfirmed\b/gi, "reported");
}
export function localInput(iso: string, tz: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
/** Resolve local wall time without using the browser timezone. Reject DST gaps/ambiguities. */
export function localToUtc(input: string, tz: string): string {
  const base = Date.parse(`${input}:00Z`);
  if (!Number.isFinite(base)) throw new Error("Enter a valid date and time");
  const candidates = new Set<string>();
  for (let offset = -14 * 60; offset <= 14 * 60; offset += 15) {
    const iso = new Date(base + offset * 60_000).toISOString();
    if (localInput(iso, tz) === input) candidates.add(iso);
  }
  if (candidates.size !== 1)
    throw new Error(
      "This local time is missing or ambiguous at a daylight-saving transition. Choose another time.",
    );
  return [...candidates][0];
}
export function centsFromInput(value: string): number {
  if (!/^\d+(\.\d{1,2})?$/.test(value))
    throw new Error("Enter dollars with at most two decimal places");
  const [d, c = ""] = value.split(".");
  const cents = Number(d) * 100 + Number(c.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents) || cents <= 0)
    throw new Error("Budget must be greater than zero");
  return cents;
}
