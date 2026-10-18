import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { buildStory } from "@/mocks/scenario";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ProviderGallery, orderProviders } from "@/components/ProviderGallery";
import { QuestionCard } from "@/components/QuestionCard";
import { api, ApiError, request, StaleProposalError } from "@/lib/api";
import type { OpenQuestion, TaskView } from "@/lib/types";

const story = () => buildStory();
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function withThirdProvider(view: TaskView): TaskView {
  view.providers = [
    ...view.providers,
    {
      id: "provider_c",
      name: "Coastal Appliance Pros",
      channel: "fixture",
      handle: "fixture:provider_c",
      portal_url: null,
    },
  ];
  return view;
}

describe("A. reject means find another", () => {
  it("declines the provider, a single time, or stops", async () => {
    const approval = story()[2].approvals[0];
    const refresh = vi.fn().mockResolvedValue(undefined);
    const approve = vi.spyOn(api, "approve").mockResolvedValue(approval);
    const cancel = vi.spyOn(api, "cancel").mockResolvedValue(story()[2].task);
    render(
      <ApprovalCard
        approval={approval}
        timezone="America/Los_Angeles"
        onRefresh={refresh}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /find another/i }));
    await waitFor(() =>
      expect(approve).toHaveBeenLastCalledWith(approval.task_id, {
        proposal_hash: approval.proposal_hash,
        decision: "rejected",
        approver: "demo_user",
        scope: "provider",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /a different time/i }));
    await waitFor(() =>
      expect(approve.mock.calls.at(-1)?.[1]).toMatchObject({
        decision: "rejected",
        scope: "proposal",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /stop here/i }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith(approval.task_id));
  });
});

describe("C. provider gallery", () => {
  it("orders proposal first, then eligible by price, then waiting", () => {
    const view = withThirdProvider(story()[2]);
    expect(orderProviders(view).map((p) => p.id)).toEqual([
      "provider_a", // the current proposal
      "provider_b",
      "provider_c", // hasn't replied yet
    ]);
  });
  it("renders labelled slides and moves with the buttons", () => {
    const view = withThirdProvider(story()[2]);
    render(<ProviderGallery view={view} onEvidence={() => undefined} />);
    const carousel = screen.getByRole("region", {
      name: "Providers in this sandbox",
    });
    expect(
      within(carousel).getAllByRole("group").map((g) => g.getAttribute("aria-label")),
    ).toEqual([
      "1 of 3: Ace Appliance Repair",
      "2 of 3: Bayside Appliance Service",
      "3 of 3: Coastal Appliance Pros",
    ]);
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next provider" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous provider" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous provider" }));
    expect(screen.getByText("3 of 3")).toBeInTheDocument(); // wraps around
    expect(screen.getByRole("button", { name: /pause sliding|slide automatically/i })).toBeInTheDocument();
  });
});

describe("F3. questions", () => {
  const question: OpenQuestion = {
    question_id: "q_1",
    text: "No provider meets your constraints. Raise the budget?",
    reason_code: "no_eligible_provider",
    asked_at: "2026-10-18T00:00:00Z",
    options: [
      {
        id: "raise_budget",
        label: "Raise the budget",
        params: { current_cents: 15000, suggested_cents: 17500 },
      },
      { id: "stop", label: "Stop here", params: {} },
    ],
  };
  it("sends the chosen budget in cents and stops when asked", async () => {
    const view = story()[2];
    const refresh = vi.fn().mockResolvedValue(undefined);
    const answer = vi.spyOn(api, "answer").mockResolvedValue(view.task);
    render(<QuestionCard view={view} question={question} onRefresh={refresh} />);
    expect(screen.getByText("No option fits your limits")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Raise the budget" }));
    expect(screen.getByDisplayValue("175")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /confirm: raise the budget/i }));
    await waitFor(() =>
      expect(answer).toHaveBeenCalledWith(view.task.id, {
        question_id: "q_1",
        choice: "raise_budget",
        params: { max_visit_charge_cents: 17500 },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop here" }));
    await waitFor(() =>
      expect(answer.mock.calls.at(-1)?.[1]).toMatchObject({ choice: "stop" }),
    );
    expect(refresh).toHaveBeenCalled();
  });
});

describe("F1. error envelope", () => {
  function respond(status: number, body: unknown) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
  }
  it("exposes the stable code and message", async () => {
    respond(409, {
      detail: "That question is no longer open.",
      error: {
        code: "stale_question",
        message: "That question is no longer open.",
        retryable: false,
        field: null,
        details: {},
      },
    });
    const err = (await request("/tasks/x/answers", {}).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("stale_question");
    expect(err.message).toBe("That question is no longer open.");
  });
  it("maps stale proposals from the envelope", async () => {
    respond(409, {
      detail: { code: "stale_proposal", current_hash: "abc", reason: "changed" },
      error: {
        code: "stale_proposal",
        message: "Terms changed since you saw them.",
        retryable: false,
        field: null,
        details: { current_hash: "abc", reason: "changed" },
      },
    });
    const err = (await request("/tasks/x/approvals", {}).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(StaleProposalError);
    expect((err as StaleProposalError).currentHash).toBe("abc");
  });
  it("reads 422 fields from either shape", async () => {
    const fields = [{ loc: ["body", "constraints", "service"], msg: "unknown service" }];
    respond(422, {
      detail: fields,
      error: {
        code: "invalid_intake",
        message: "Some details need attention.",
        retryable: false,
        field: "constraints.service",
        details: { fields },
      },
    });
    const err = (await request("/tasks", {}).catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("invalid_intake");
    expect(err.fields[0].msg).toBe("unknown service");
  });
  it("sends the sign-in cookie with every request", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetcher);
    await request("/auth/me");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });
});
