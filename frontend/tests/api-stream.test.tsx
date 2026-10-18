import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, request, StaleProposalError } from "@/lib/api";
import { mergeTimeline, useTaskStream } from "@/lib/useTaskStream";
import { buildStory } from "@/mocks/scenario";
import type { TimelineEvent } from "@/lib/types";
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("retains server field errors and typed stale proposal details", async () => {
  const fields = [
    {
      loc: ["body", "constraints", "window_end"],
      msg: "End must follow start",
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({ detail: fields }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          detail: {
            code: "stale_proposal",
            current_hash: "new",
            reason: "price changed",
          },
        }),
      }),
  );
  const fieldError = await request("/tasks", {}).catch((e) => e);
  expect(fieldError).toBeInstanceOf(ApiError);
  if (!(fieldError instanceof ApiError)) throw new Error("Expected ApiError");
  expect(fieldError.fields).toEqual(fields);
  const stale = await request("/tasks/tsk/approvals", {}).catch((e) => e);
  expect(stale).toBeInstanceOf(StaleProposalError);
  if (!(stale instanceof StaleProposalError))
    throw new Error("Expected stale proposal");
  expect(stale.currentHash).toBe("new");
});
it("merges replayed timeline events without duplicates", () => {
  const timeline = buildStory()[2].timeline;
  expect(mergeTimeline(timeline, [timeline[1], timeline[0]])).toEqual(timeline);
});
it("resumes SSE from the snapshot sequence, refreshes, and closes on unmount", async () => {
  class Source extends EventTarget {
    static instances: Source[] = [];
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor(public url: string) {
      super();
      Source.instances.push(this);
    }
  }
  vi.stubGlobal("EventSource", Source);
  const view = buildStory()[1];
  const fetcher = vi.spyOn(api, "task").mockResolvedValue(view);
  const { result, unmount } = renderHook(() => useTaskStream(view.task.id));
  await waitFor(() => expect(Source.instances).toHaveLength(1));
  const source = Source.instances[0];
  expect(source.url).toContain(`after_seq=${view.timeline.at(-1)!.seq}`);
  act(() => source.onopen?.());
  await waitFor(() => expect(result.current.connection).toBe("connected"));
  const event: TimelineEvent = {
    ...view.timeline[0],
    id: "tl_new",
    seq: 50,
    message: "New source arrived",
  };
  act(() =>
    source.dispatchEvent(
      new MessageEvent("timeline", { data: JSON.stringify(event) }),
    ),
  );
  expect(result.current.view?.timeline.at(-1)?.seq).toBe(50);
  await waitFor(() =>
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(3),
  );
  act(() => source.onerror?.());
  expect(result.current.connection).toBe("reconnecting");
  await waitFor(() => expect(Source.instances).toHaveLength(2), {
    timeout: 2000,
  });
  expect(Source.instances[1].url).toContain("after_seq=50");
  unmount();
  expect(Source.instances[1].close).toHaveBeenCalled();
});
