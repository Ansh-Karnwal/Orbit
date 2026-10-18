"use client";
import { useEffect, useState } from "react";
import { HelpCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { centsFromInput, localInput, localToUtc, money } from "@/lib/format";
import { REASON_LABELS } from "@/lib/labels";
import type {
  OpenQuestion,
  ProviderSpec,
  QuestionOption,
  TaskView,
} from "@/lib/types";

/** Orbit is blocked and asks the user: show the question and its offered choices (F3). */
export function QuestionCard({
  view,
  question,
  onRefresh,
}: {
  view: TaskView;
  question: OpenQuestion;
  onRefresh: () => Promise<void>;
}) {
  // The workspace keys this card by question id, so these initialisers run once per question.
  const tz = view.task.constraints.timezone;
  const option = (id: QuestionOption["id"]) =>
    question.options.find((o) => o.id === id);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [open, setOpen] = useState<QuestionOption["id"] | null>(null),
    [budget, setBudget] = useState(() =>
      String(Number(option("raise_budget")?.params.suggested_cents ?? 0) / 100),
    ),
    [start, setStart] = useState(() => {
      const w = option("widen_window");
      return w ? localInput(String(w.params.window_start), tz) : "";
    }),
    [end, setEnd] = useState(() => {
      const w = option("widen_window");
      return w ? localInput(String(w.params.window_end), tz) : "";
    }),
    [reconsider, setReconsider] = useState(
      () =>
        ((option("reconsider")?.params.provider_ids as string[] | undefined) ??
          [])[0] ?? "",
    ),
    [sandbox, setSandbox] = useState<ProviderSpec[]>([]),
    [newProvider, setNewProvider] = useState(""),
    [customName, setCustomName] = useState(""),
    [customHandle, setCustomHandle] = useState("");
  const names = new Map(view.providers.map((p) => [p.id, p.name]));
  const wantsProviders = question.options.some((o) => o.id === "add_provider");
  const taken = view.providers.map((p) => p.id).join(",");

  useEffect(() => {
    if (!wantsProviders) return;
    let active = true;
    api
      .sandboxProviders()
      .then((all) => {
        if (active) setSandbox(all.filter((p) => !taken.split(",").includes(p.id)));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [wantsProviders, taken]);

  async function answer(choice: QuestionOption["id"]) {
    setBusy(true);
    setError("");
    try {
      let params: Record<string, unknown> = {};
      if (choice === "raise_budget")
        params = { max_visit_charge_cents: centsFromInput(budget) };
      if (choice === "widen_window")
        params = {
          window_start: localToUtc(start, tz),
          window_end: localToUtc(end, tz),
        };
      if (choice === "reconsider") params = { provider_id: reconsider };
      if (choice === "add_provider") {
        const picked = sandbox.find((p) => p.id === newProvider);
        const custom = customName.trim() && customHandle.trim();
        if (!picked && !custom)
          throw new Error("Pick a sandbox provider or enter a name and handle.");
        params = {
          provider: picked ?? {
            id: `custom_${customName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_")}`,
            name: customName.trim(),
            channel: customHandle.trim().startsWith("fixture:") ? "fixture" : "imessage",
            handle: customHandle.trim(),
            portal_url: null,
          },
        };
      }
      await api.answer(view.task.id, {
        question_id: question.question_id,
        choice,
        params,
      });
      setOpen(null);
      await onRefresh();
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "stale_question"
          ? "That question was already resolved — refreshing."
          : e instanceof Error
            ? e.message
            : "Could not send your answer",
      );
      if (e instanceof ApiError && e.code === "stale_question") await onRefresh();
    } finally {
      setBusy(false);
    }
  }

  const needsInput = new Set(["raise_budget", "widen_window", "reconsider", "add_provider"]);
  return (
    <section className="card question-card" aria-labelledby="question-title">
      <div className="section-title">
        <div className="row">
          <HelpCircle size={18} />
          <h2 id="question-title">Orbit needs you</h2>
        </div>
        <span className="badge amber">{REASON_LABELS[question.reason_code]}</span>
      </div>
      <p className="question-text">{question.text}</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="question-options">
        {question.options.map((o) =>
          needsInput.has(o.id) ? (
            <div key={o.id} className={`question-option ${open === o.id ? "open" : ""}`}>
              <button
                className="button"
                aria-expanded={open === o.id}
                disabled={busy}
                onClick={() => setOpen(open === o.id ? null : o.id)}
              >
                {o.label}
              </button>
              {open === o.id && (
                <div className="question-form stack">
                  {o.id === "raise_budget" && (
                    <label className="field">
                      New max visit charge (USD) — now{" "}
                      {money(Number(o.params.current_cents ?? 0))}
                      <div className="input-with-prefix">
                        <span className="input-prefix">$</span>
                        <input
                          inputMode="decimal"
                          value={budget}
                          onChange={(e) => setBudget(e.target.value)}
                        />
                      </div>
                    </label>
                  )}
                  {o.id === "widen_window" && (
                    <div className="grid-two">
                      <label className="field">
                        Window starts
                        <input
                          type="datetime-local"
                          value={start}
                          onChange={(e) => setStart(e.target.value)}
                        />
                      </label>
                      <label className="field">
                        Window ends
                        <input
                          type="datetime-local"
                          value={end}
                          onChange={(e) => setEnd(e.target.value)}
                        />
                      </label>
                    </div>
                  )}
                  {o.id === "reconsider" && (
                    <label className="field">
                      Provider to reconsider
                      <select
                        value={reconsider}
                        onChange={(e) => setReconsider(e.target.value)}
                      >
                        {((o.params.provider_ids as string[]) ?? []).map((id) => (
                          <option key={id} value={id}>
                            {names.get(id) ?? id}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {o.id === "add_provider" && (
                    <>
                      {sandbox.length > 0 && (
                        <label className="field">
                          From the sandbox
                          <select
                            value={newProvider}
                            onChange={(e) => setNewProvider(e.target.value)}
                          >
                            <option value="">— choose —</option>
                            {sandbox.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      <div className="grid-two">
                        <label className="field">
                          Or a new provider&apos;s name
                          <input
                            value={customName}
                            onChange={(e) => setCustomName(e.target.value)}
                          />
                        </label>
                        <label className="field">
                          Their handle
                          <input
                            value={customHandle}
                            placeholder="fixture:name or a phone number"
                            onChange={(e) => setCustomHandle(e.target.value)}
                          />
                        </label>
                      </div>
                    </>
                  )}
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void answer(o.id)}
                  >
                    {busy ? "Sending…" : `Confirm: ${o.label.toLowerCase()}`}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              key={o.id}
              className={`button ${o.id === "stop" ? "danger-outline" : "primary"}`}
              disabled={busy}
              onClick={() => void answer(o.id)}
            >
              {o.label}
            </button>
          ),
        )}
      </div>
    </section>
  );
}
