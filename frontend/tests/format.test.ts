import { describe, it, expect } from "vitest";
import {
  centsFromInput,
  claimLabel,
  localRange,
  localToUtc,
  money,
  safeWording,
} from "@/lib/format";
import { buildStory } from "@/mocks/scenario";
describe("formatting and evidence wording", () => {
  it("uses integer cents", () => {
    expect(money(14500)).toBe("$145.00");
    expect(centsFromInput("0.29")).toBe(29);
    expect(() => money(1.2)).toThrow();
    expect(() => centsFromInput("1.001")).toThrow();
  });
  it("shows both timezone offsets across DST", () => {
    expect(
      localRange(
        "2026-11-01T08:30:00Z",
        "2026-11-01T09:30:00Z",
        "America/Los_Angeles",
      ),
    ).toContain("1:30 AM PDT–1:30 AM PST");
  });
  it("resolves timezone independently of the host and rejects DST gaps", () => {
    expect(localToUtc("2026-10-20T14:00", "America/Los_Angeles")).toBe(
      "2026-10-20T21:00:00.000Z",
    );
    expect(() =>
      localToUtc("2026-03-08T02:30", "America/Los_Angeles"),
    ).toThrow();
    expect(() =>
      localToUtc("2026-11-01T01:30", "America/Los_Angeles"),
    ).toThrow();
  });
  it("does not upgrade evidence claims without PASS", () => {
    expect(claimLabel("booking_verified")).toBe("Verification pending");
    expect(claimLabel("booking_request_submitted", "PASS")).toBe(
      "Booking request submitted",
    );
    expect(claimLabel("booking_verified", "PASS")).toBe("Booking verified");
    expect(safeWording("Handled, booked and confirmed")).not.toMatch(
      /\b(handled|booked|confirmed)\b/i,
    );
  });
  it("contains all story phases with immutable history", () => {
    const story = buildStory();
    expect(story).toHaveLength(7);
    expect(story[2].approvals[0].status).toBe("requested");
    expect(story[3].approvals[0].status).toBe("invalidated");
    expect(
      story[3].facts.filter((f) => f.key === "provider_a.visit_charge_cents"),
    ).toHaveLength(2);
    expect(story[6].verification?.verdict).toBe("PASS");
  });
});
