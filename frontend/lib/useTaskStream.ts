"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, USE_MOCKS } from "./api";
import type { TaskView, TimelineEvent } from "./types";
export function mergeTimeline(
  a: TimelineEvent[],
  b: TimelineEvent[],
): TimelineEvent[] {
  return [...new Map([...a, ...b].map((e) => [e.seq, e])).values()]
    .sort((x, y) => x.seq - y.seq)
    .slice(-200);
}
export function useTaskStream(id: string) {
  const [view, setView] = useState<TaskView | null>(null),
    [error, setError] = useState<string | null>(null),
    [connection, setConnection] = useState<
      "connecting" | "connected" | "reconnecting"
    >("connecting");
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const refresh = useCallback(() => refreshRef.current(), []);
  useEffect(() => {
    let disposed = false,
      source: EventSource | null = null,
      unsubscribe: (() => void) | undefined,
      retry = 0,
      lastSeq = 0,
      generation = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined,
      debounce: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    const fetchView = async () => {
      const requestGeneration = ++generation;
      try {
        const next = await api.task(id, abort.signal);
        if (disposed || requestGeneration !== generation) return;
        lastSeq = Math.max(lastSeq, ...next.timeline.map((e) => e.seq));
        setView((previous) => ({
          ...next,
          timeline: mergeTimeline(
            previous?.task.id === id ? previous.timeline : [],
            next.timeline,
          ),
        }));
        setError(null);
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : "Unable to load task");
          throw e;
        }
      }
    };
    refreshRef.current = fetchView;
    const connect = () => {
      if (disposed) return;
      source = new EventSource(api.eventsUrl(id, lastSeq));
      source.onopen = () => {
        retry = 0;
        setConnection("connected");
        void fetchView().catch(() => {});
      };
      source.addEventListener("timeline", (message: MessageEvent<string>) => {
        try {
          const event = JSON.parse(message.data) as TimelineEvent;
          if (
            event.task_id !== id ||
            !Number.isInteger(event.seq) ||
            event.seq <= lastSeq
          )
            return;
          lastSeq = event.seq;
          setView((old) =>
            old
              ? { ...old, timeline: mergeTimeline(old.timeline, [event]) }
              : old,
          );
          if (!debounce)
            debounce = setTimeout(() => {
              debounce = undefined;
              void fetchView().catch(() => {});
            }, 250);
        } catch {
          setError("An update could not be read. Refreshing task.");
          void fetchView().catch(() => {});
        }
      });
      source.onerror = () => {
        source?.close();
        setConnection("reconnecting");
        reconnectTimer = setTimeout(
          connect,
          Math.min(1000 * 2 ** retry++, 15000),
        );
      };
    };
    const start = async () => {
      try {
        await fetchView();
        if (disposed) return;
        if (USE_MOCKS) {
          const { mock } = await import("@/mocks/store");
          if (disposed) return;
          unsubscribe = mock.subscribe(id, () => {
            void fetchView().catch(() => {});
          });
          setConnection("connected");
        } else connect();
      } catch {
        if (!disposed) {
          setConnection("reconnecting");
          reconnectTimer = setTimeout(
            start,
            Math.min(1000 * 2 ** retry++, 15000),
          );
        }
      }
    };
    void start();
    return () => {
      disposed = true;
      abort.abort();
      source?.close();
      unsubscribe?.();
      clearTimeout(reconnectTimer);
      clearTimeout(debounce);
    };
  }, [id]);
  return {
    view: view?.task.id === id ? view : null,
    error,
    connection,
    refresh,
  };
}
