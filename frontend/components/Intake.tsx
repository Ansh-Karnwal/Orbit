"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  FileInput,
  LockKeyhole,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { centsFromInput, localInput, localToUtc } from "@/lib/format";
import { parseCreao, taskCreateSchema } from "@/lib/intake";
import { LandingHero } from "./LandingHero";
import type { Health, TaskCreate } from "@/lib/types";
export default function Intake() {
  const router = useRouter();
  const [seed, setSeed] = useState<TaskCreate | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [outcome, setOutcome] = useState(""),
    [service, setService] = useState("dishwasher_repair"),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [budget, setBudget] = useState("150"),
    [mode, setMode] = useState<"fixture" | "live">("fixture"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [fields, setFields] = useState<Record<string, string>>({}),
    [json, setJson] = useState(""),
    [reference, setReference] = useState(""),
    [imported, setImported] = useState(false);
  function fill(value: TaskCreate) {
    setSeed(value);
    setOutcome(value.outcome_text);
    setService(value.constraints.service);
    setStart(
      localInput(value.constraints.window_start, value.constraints.timezone),
    );
    setEnd(
      localInput(value.constraints.window_end, value.constraints.timezone),
    );
    setBudget(String(value.constraints.max_visit_charge_cents / 100));
    setMode(value.mode);
  }
  useEffect(() => {
    let active = true;
    void Promise.all([api.seed(), api.health()])
      .then(([s, h]) => {
        if (active) {
          fill(s);
          setHealth(h);
        }
      })
      .catch((e) => {
        if (active)
          setError(
            e instanceof Error ? e.message : "Could not load the demo seed",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  const canLive =
    health?.ok &&
    health.integrations.photon === "live" &&
    health.integrations.browser_use === "live" &&
    seed?.providers.every(
      (p) => p.channel !== "fixture" && !p.handle.startsWith("fixture:"),
    );
  const zone = seed?.constraints.timezone ?? "America/Los_Angeles";
  const fieldError = (key: string) =>
    fields[key] ? (
      <span className="field-error" role="alert">
        {fields[key]}
      </span>
    ) : null;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setFields({});
    if (!seed) return;
    try {
      const f: Record<string, string> = {};
      let window_start = "",
        window_end = "",
        cents = 0;
      try {
        window_start = localToUtc(start, zone);
      } catch (e) {
        f["constraints.window_start"] = (e as Error).message;
      }
      try {
        window_end = localToUtc(end, zone);
      } catch (e) {
        f["constraints.window_end"] = (e as Error).message;
      }
      try {
        cents = centsFromInput(budget);
      } catch (e) {
        f["constraints.max_visit_charge_cents"] = (e as Error).message;
      }
      if (Object.keys(f).length) {
        setFields(f);
        return;
      }
      const parsed = taskCreateSchema.safeParse({
        ...seed,
        outcome_text: outcome,
        constraints: {
          ...seed.constraints,
          service,
          window_start,
          window_end,
          max_visit_charge_cents: cents,
        },
        mode,
        source: imported ? "creao" : "manual",
      });
      if (!parsed.success) {
        setFields(
          Object.fromEntries(
            parsed.error.issues.map((i) => [i.path.join("."), i.message]),
          ),
        );
        return;
      }
      if (mode === "live" && !canLive)
        throw new Error("Live providers and integrations are not ready.");
      setBusy(true);
      const view = await api.create(parsed.data);
      router.push(`/tasks/${view.task.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setFields(
          Object.fromEntries(
            e.fields.map((f) => [
              f.loc.filter((x) => x !== "body").join("."),
              f.msg,
            ]),
          ),
        );
        setError(
          e.fields.length
            ? e.fields.map((field) => field.msg).join(" ")
            : e.message,
        );
      } else setError(e instanceof Error ? e.message : "Could not start task");
    } finally {
      setBusy(false);
    }
  }
  function importJson() {
    try {
      const value = parseCreao(json, reference);
      fill(value);
      setImported(true);
      setFields({});
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid CREAO JSON");
    }
  }
  return (
    <main id="main" className="landing-main">
      <LandingHero />
      <section
        className="intake-section"
        id="intake"
        aria-labelledby="intake-title"
      >
        <div className="intake-heading">
          <div>
            <h2 id="intake-title">Set your outcome</h2>
          </div>
        </div>
        <div className="intake-grid">
          <section
            className="card intake-card"
            aria-label="Create a repair coordination task"
          >
            <div className="section-title">
              <h2>Outcome details</h2>
            </div>
            {error && (
              <p className="error break" role="alert">
                {error}
              </p>
            )}
            {!seed ? (
              <p className="empty">
                {error
                  ? "The backend seed is unavailable. Start the backend or enable NEXT_PUBLIC_USE_MOCKS=1."
                  : "Loading defaults…"}
              </p>
            ) : (
              <form onSubmit={submit} className="stack" noValidate>
                <div className="field">
                  <label htmlFor="outcome-input">Desired outcome</label>
                  <textarea
                    id="outcome-input"
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value)}
                    placeholder="Describe what needs to be scheduled or repaired…"
                    rows={3}
                    required
                  />
                  {fieldError("outcome_text")}
                </div>
                <div className="grid-two">
                  <label className="field">
                    Service category
                    <select
                      value={service}
                      onChange={(e) => setService(e.target.value)}
                    >
                      <option value="dishwasher_repair">
                        Dishwasher repair
                      </option>
                    </select>
                    {fieldError("constraints.service")}
                  </label>
                  <label className="field">
                    Max visit charge (USD)
                    <div className="input-with-prefix">
                      <span className="input-prefix">$</span>
                      <input
                        inputMode="decimal"
                        value={budget}
                        onChange={(e) => setBudget(e.target.value)}
                        placeholder="150"
                      />
                    </div>
                    {fieldError("constraints.max_visit_charge_cents")}
                  </label>
                </div>
                <div className="grid-two">
                  <label className="field">
                    Window starts
                    <input
                      type="datetime-local"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                    {fieldError("constraints.window_start")}
                  </label>
                  <label className="field">
                    Window ends
                    <input
                      type="datetime-local"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                    {fieldError("constraints.window_end")}
                  </label>
                </div>
                {fieldError("constraints")}
                <div className="permission-note">
                  <LockKeyhole size={16} />
                  <span>You approve the provider and terms before booking.</span>
                </div>
                <div>
                  <p className="field-title">Candidate Providers</p>
                  <div className="provider-pill-list">
                    {seed.providers.map((p) => (
                      <div key={p.id} className="provider-pill-item">
                        <span className="provider-initial">
                          {p.name.charAt(0)}
                        </span>
                        <span className="provider-name">{p.name}</span>
                        <span className="provider-mode-dot" />
                      </div>
                    ))}
                  </div>
                  {fieldError("providers")}
                </div>
                <div className="row between wrap mode-row">
                  <div className="mode-toggle">
                    <label className={`mode-btn ${mode === "fixture" ? "active" : ""}`}>
                      <input
                        type="radio"
                        name="mode"
                        checked={mode === "fixture"}
                        onChange={() => setMode("fixture")}
                      />
                      Fixture Sandbox
                    </label>
                    <label className={`mode-btn ${mode === "live" ? "active" : ""} ${!canLive ? "disabled" : ""}`}>
                      <input
                        type="radio"
                        name="mode"
                        checked={mode === "live"}
                        disabled={!canLive}
                        onChange={() => setMode("live")}
                      />
                      Live Execution
                    </label>
                  </div>
                </div>
                {imported && (
                  <p className="notice">
                    <Check size={16} />
                    CREAO JSON imported
                  </p>
                )}
                <button className="button primary large submit-btn" disabled={busy}>
                  {busy ? "Starting coordination…" : "Start coordinating"}
                  <ArrowRight size={18} />
                </button>
              </form>
            )}
          </section>
          <aside className="stack">
            <details className="card aside-import-card">
              <summary>
                <span className="row">
                  <FileInput size={16} />
                  Import CREAO JSON
                  <ArrowUpRight size={14} />
                </span>
              </summary>
              <div className="stack aside-import-body">
                <label className="field">
                  Reference link
                  <input
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                    placeholder="Optional workflow reference"
                  />
                </label>
                <label className="field">
                  TaskCreate JSON
                  <textarea
                    value={json}
                    onChange={(e) => setJson(e.target.value)}
                    className="mono"
                    placeholder={
                      '{"outcome_text": "…", "constraints": {…}, "providers": […]}'
                    }
                    rows={4}
                  />
                </label>
                <button
                  type="button"
                  className="button"
                  disabled={!json.trim()}
                  onClick={importJson}
                >
                  Apply intake payload
                </button>
              </div>
            </details>
          </aside>
        </div>
      </section>
    </main>
  );
}
