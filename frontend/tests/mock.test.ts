import { it, expect } from "vitest";
import { mock } from "@/mocks/store";
import { PRICE_CHANGE } from "@/mocks/scenario";
function start() {
  const id = mock.create(mock.seed()).task.id;
  mock.tick(id);
  mock.tick(id);
  return id;
}
function toB(id: string) {
  mock.inject({
    task_id: id,
    provider_id: "provider_a",
    text: PRICE_CHANGE,
    external_id: "change",
  });
  mock.tick(id);
}
it("stopping a mock request withdraws approval and rejects a later decision", () => {
  const id = start();
  const approval = mock.get(id).approvals[0];
  mock.cancel(id);
  expect(mock.get(id).approvals[0].status).toBe("invalidated");
  expect(() =>
    mock.approve(id, {
      proposal_hash: approval.proposal_hash,
      decision: "approved",
      approver: "test",
    }),
  ).toThrow("Terms changed");
  mock.tick(id);
  expect(mock.get(id).task.status).toBe("CANCELLED");
});
it("pauses without auto approval, rejects stale hashes and deduplicates", () => {
  const id = start();
  const a = mock.get(id).approvals[0];
  mock.tick(id);
  expect(mock.get(id).approvals[0].status).toBe("requested");
  toB(id);
  expect(() =>
    mock.approve(id, {
      proposal_hash: a.proposal_hash,
      decision: "approved",
      approver: "test",
    }),
  ).toThrow("Terms changed");
  expect(
    mock.inject({
      task_id: id,
      provider_id: "provider_a",
      text: PRICE_CHANGE,
      external_id: "change",
    }).created,
  ).toBe(false);
  expect(mock.get(id).timeline.at(-1)?.type).toBe("message.duplicate_ignored");
});
it.each([
  "mismatch",
  "no_confirmation",
  "down",
  "timeout_after_submit",
] as const)("exercises %s without false completion", (fault) => {
  const id = start();
  toB(id);
  mock.fault(fault);
  const b = mock.get(id).approvals.at(-1)!;
  mock.approve(id, {
    proposal_hash: b.proposal_hash,
    decision: "approved",
    approver: "test",
  });
  mock.tick(id);
  const view = mock.get(id);
  expect(view.verification?.verdict).toBe(
    fault === "timeout_after_submit"
      ? "PASS"
      : fault === "mismatch"
        ? "FAIL"
        : "INSUFFICIENT_EVIDENCE",
  );
  expect(view.task.status === "COMPLETED").toBe(
    fault === "timeout_after_submit",
  );
});

it("binds mock approval hashes to full proposal contents", async () => {
  const { mockProposalHash } = await import("@/mocks/hash");
  const { createHash } = await import("node:crypto");
  const id = start();
  const approval = mock.get(id).approvals[0];
  const sorted = Object.fromEntries(
    Object.entries(approval.proposal).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    ),
  );
  expect(approval.proposal_hash).toBe(
    createHash("sha256").update(JSON.stringify(sorted)).digest("hex"),
  );
  expect(
    mockProposalHash({ ...approval.proposal, visit_charge_cents: 19000 }),
  ).not.toBe(approval.proposal_hash);
});
