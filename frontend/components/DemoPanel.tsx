"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, RotateCcw, Zap } from "lucide-react";
import { api, USE_MOCKS } from "@/lib/api";
import { PRICE_CHANGE } from "@/mocks/scenario";
import type { DemoInjectIn, PortalFaultIn, TaskView } from "@/lib/types";
export default function DemoPanel({
  view,
  enabled,
  onRefresh,
}: {
  view: TaskView;
  enabled: boolean;
  onRefresh: () => Promise<void>;
}) {
  const router = useRouter(),
    lock = useRef(false);
  const [last, setLast] = useState<DemoInjectIn | null>(null);
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [fault, setFault] = useState<PortalFaultIn["mode"]>("none"),
    [target, setTarget] = useState(view.providers[0]?.id ?? "provider_a"),
    [customText, setCustomText] = useState("");
  const act = useCallback(async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setMessage("");
    try {
      await action();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Demo control failed");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }, []);
  const inject = useCallback(
    () =>
      act(async () => {
        const body = {
          task_id: view.task.id,
          provider_id: "provider_a",
          text: PRICE_CHANGE,
          external_id: `demo_price_${crypto.randomUUID()}`,
        };
        await api.inject(body);
        setLast(body);
        await onRefresh();
        setMessage(
          "Price change injected. Watch the approval and plan update.",
        );
      }),
    [act, onRefresh, view.task.id],
  );
  const injectCustom = useCallback(
    () =>
      act(async () => {
        if (!customText.trim()) throw new Error("Type the provider's message first.");
        const body = {
          task_id: view.task.id,
          provider_id: target,
          text: customText.trim(),
          external_id: `demo_msg_${crypto.randomUUID()}`,
        };
        await api.inject(body);
        setLast(body);
        await onRefresh();
        const name = view.providers.find((p) => p.id === target)?.name ?? target;
        setMessage(`Message from ${name} injected.`);
      }),
    [act, customText, onRefresh, target, view.providers, view.task.id],
  );
  const reset = useCallback(
    () =>
      act(async () => {
        const result = await api.reset({ create_task: true, mode: "fixture" });
        if (result.task_id) router.push(`/tasks/${result.task_id}?demo=1`);
      }),
    [act, router],
  );
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.closest('input,textarea,select,[contenteditable="true"]') ||
        !e.shiftKey ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        e.repeat
      )
        return;
      if (e.code === "Digit1") {
        e.preventDefault();
        void inject();
      }
      if (e.code === "KeyR") {
        e.preventDefault();
        void reset();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled, inject, reset]);
  if (!enabled) return null;
  return (
    <details className="card demo-panel">
      <summary>
        <span className="row">
          <FlaskConical size={17} />
          Presenter controls
          <span className="badge">
            {USE_MOCKS ? "Offline mock" : "Backend demo"}
          </span>
        </span>
      </summary>
      <div className="demo-controls">
        <button
          className="button"
          disabled={busy}
          onClick={() => void inject()}
        >
          <Zap size={15} />
          Inject: Provider A adds $70 trip charge <kbd>⇧ 1</kbd>
        </button>
        <button
          className="button"
          disabled={busy || !last}
          onClick={() =>
            void act(async () => {
              if (!last) return;
              await api.inject(last);
              await api.inject(last);
              await onRefresh();
              setMessage(
                "Repeated the last external ID twice. Look for duplicate ignored events.",
              );
            })
          }
        >
          Inject duplicate of last message
        </button>
        <button className="button" disabled={busy} onClick={() => void reset()}>
          <RotateCcw size={15} />
          Reset demo <kbd>⇧ R</kbd>
        </button>
      </div>
      {!USE_MOCKS && (
        <div className="demo-custom stack">
          <div className="grid-two">
            <label className="field">
              A provider replies
              <select
                value={target}
                disabled={busy}
                onChange={(e) => setTarget(e.target.value)}
              >
                {view.providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Their message
              <input
                value={customText}
                disabled={busy}
                placeholder="e.g. Diagnostic visit is $140 including travel. Tuesday 4–5pm."
                onChange={(e) => setCustomText(e.target.value)}
              />
            </label>
          </div>
          <button
            className="button"
            disabled={busy || !customText.trim()}
            onClick={() => void injectCustom()}
          >
            <Zap size={15} />
            Inject this message
          </button>
        </div>
      )}
      <label className="field">
        Portal fault (set before approving Bayside)
        <select
          value={fault}
          disabled={busy}
          onChange={(e) => {
            const mode = e.target.value as PortalFaultIn["mode"];
            void act(async () => {
              await api.fault({ mode });
              setFault(mode);
              setMessage(
                `Portal fault: ${mode}. Reset after a completed run to replay.`,
              );
            });
          }}
        >
          {[
            "none",
            "timeout_after_submit",
            "mismatch",
            "no_confirmation",
            "down",
          ].map((mode) => (
            <option value={mode} key={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
    </details>
  );
}
