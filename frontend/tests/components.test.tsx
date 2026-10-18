import React from "react";
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { buildStory } from "@/mocks/scenario";
import { FixtureBanner } from "@/components/FixtureBanner";
import { FactHistory } from "@/components/ProviderCard";
import { ApprovalCard } from "@/components/ApprovalCard";
import { CompletionSummary } from "@/components/VerificationPanel";
import { OrbitLoop } from "@/components/OrbitLoop";
import { api, StaleProposalError } from "@/lib/api";
const story = () => buildStory();
describe("evidence and approval requirements", () => {
  it.each(["task", "evidence", "integration"])(
    "labels fixtures triggered by %s",
    (trigger) => {
      const view = story()[0];
      view.task.mode = "live";
      view.integrations = {};
      view.evidence = [];
      if (trigger === "task") view.task.mode = "fixture";
      if (trigger === "evidence") view.evidence = story()[1].evidence;
      if (trigger === "integration")
        view.integrations = { browser_use: "fixture" };
      render(<FixtureBanner view={view} />);
      expect(screen.getByText("FIXTURE MODE")).toBeInTheDocument();
    },
  );
  it("does not label entirely live evidence as fixture", () => {
    const view = story()[0];
    view.task.mode = "live";
    view.integrations = { photon: "live" };
    render(<FixtureBanner view={view} />);
    expect(screen.queryByText("FIXTURE MODE")).not.toBeInTheDocument();
  });
  it("strikes superseded values and retains source links", () => {
    const view = story()[3];
    const onEvidence = vi.fn();
    render(
      <FactHistory
        facts={view.facts.filter(
          (f) => f.key === "provider_a.visit_charge_cents",
        )}
        timezone={view.task.constraints.timezone}
        onEvidence={onEvidence}
      />,
    );
    expect(screen.getByText("$120.00").tagName).toBe("DEL");
    fireEvent.click(screen.getByText("$190.00"));
    expect(onEvidence).toHaveBeenCalledWith("evd_a2");
  });
  it("posts exactly the displayed hash and refreshes on stale proposal", async () => {
    const approval = story()[2].approvals[0];
    const refresh = vi.fn().mockResolvedValue(undefined);
    const spy = vi
      .spyOn(api, "approve")
      .mockRejectedValue(new StaleProposalError("new", "changed"));
    render(
      <ApprovalCard
        approval={approval}
        timezone="America/Los_Angeles"
        onRefresh={refresh}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Approve these terms" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Terms changed"),
    );
    expect(spy).toHaveBeenCalledWith(approval.task_id, {
      proposal_hash: approval.proposal_hash,
      decision: "approved",
      approver: "demo_user",
    });
    expect(refresh).toHaveBeenCalled();
    spy.mockRestore();
  });
  it.each(["PASS", "FAIL", "INSUFFICIENT_EVIDENCE", null] as const)(
    "gates completion for verdict %s",
    (verdict) => {
      const view = story()[6];
      if (verdict) view.verification!.verdict = verdict;
      else view.verification = null;
      render(<CompletionSummary view={view} />);
      expect(!!screen.queryByText("Handled ✓")).toBe(verdict === "PASS");
    },
  );
  it("also requires task COMPLETED", () => {
    const view = story()[6];
    view.task.status = "VERIFYING";
    render(<CompletionSummary view={view} />);
    expect(screen.queryByText("Handled ✓")).toBeNull();
  });
  it("renders OrbitLoop stations and core nucleus", () => {
    const view = story()[0];
    render(<OrbitLoop view={view} />);
    expect(screen.getByText("ORBIT CORE")).toBeInTheDocument();
    expect(screen.getByText("01 · BOUNDS")).toBeInTheDocument();
    expect(screen.getByText("02 · PROVIDERS")).toBeInTheDocument();
    expect(screen.getByText("03 · DECISION GATE")).toBeInTheDocument();
    expect(screen.getByText("04 · VERIFICATION")).toBeInTheDocument();
  });
});
