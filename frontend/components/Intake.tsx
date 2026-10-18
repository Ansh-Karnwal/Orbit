"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Check, LockKeyhole } from "lucide-react";
import { api, ApiError, USE_MOCKS } from "@/lib/api";
import {
  centsFromInput,
  localInput,
  localRange,
  localToUtc,
  money,
} from "@/lib/format";
import { parseCreao, taskCreateSchema } from "@/lib/intake";
import { LandingHero } from "./LandingHero";
import type { Health, TaskCreate } from "@/lib/types";

export default function Intake() {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const errorSummary = useRef<HTMLDivElement>(null);
  const [seed, setSeed] = useState<TaskCreate | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [outcome, setOutcome] = useState("");
  const [service, setService] = useState("dishwasher_repair");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [budget, setBudget] = useState("150");
  const [mode, setMode] = useState<"fixture" | "live">("fixture");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [json, setJson] = useState("");
  const [reference, setReference] = useState("");
  const [imported, setImported] = useState(false);
  const [revision, setRevision] = useState("");
  const [attempt, setAttempt] = useState(0);
  function fill(value: TaskCreate) {
    setSeed(value);
    setOutcome(value.outcome_text.split("\nAppointment window:")[0]);
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
    const revise = new URLSearchParams(window.location.search).get("revise");
    void Promise.all([
      api.seed(),
      api.health(),
      revise ? api.task(revise) : Promise.resolve(null),
    ])
      .then(([s, h, previous]) => {
        if (!active) return;
        if (previous) {
          fill({
            ...s,
            outcome_text: previous.task.outcome_text,
            constraints: previous.task.constraints,
            providers: previous.providers,
            limits: previous.task.limits,
            mode: previous.task.mode,
          });
          setRevision(previous.task.id);
        } else
          fill({
            ...s,
            outcome_text:
              "Arrange a dishwasher diagnostic visit. Ask me before booking.",
          });
        setHealth(h);
        setError("");
      })
      .catch(() => {
        if (active)
          setError(
            "We couldn’t load this request. Check the connection and try again.",
          );
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  useEffect(() => {
    if (Object.keys(fields).length) {
      const first = form.current?.querySelector<HTMLElement>(
        '[aria-invalid="true"]',
      );
      (first ?? errorSummary.current)?.focus();
    }
  }, [fields]);
  const canLive =
    health?.ok &&
    health.integrations.photon === "live" &&
    health.integrations.browser_use === "live" &&
    seed?.providers.every(
      (p) => p.channel !== "fixture" && !p.handle.startsWith("fixture:"),
    );
  const zone = seed?.constraints.timezone ?? "America/Los_Angeles";
  const errorProps = (key: string) => ({
    "aria-invalid": !!fields[key],
    "aria-describedby": fields[key] ? `error-${key}` : undefined,
  });
  const fieldError = (key: string) =>
    fields[key] ? (
      <span id={`error-${key}`} className="field-error">
        {fields[key]}
      </span>
    ) : null;
  let boundaries = "Choose a time window and maximum visit charge.";
  let resolvedStart = "",
    resolvedEnd = "",
    cents = 0;
  try {
    resolvedStart = localToUtc(start, zone);
    resolvedEnd = localToUtc(end, zone);
    cents = centsFromInput(budget);
    boundaries = `${localRange(resolvedStart, resolvedEnd, zone)} · ${money(cents)} maximum visit charge.`;
  } catch {
    /* Invalid fields are explained when submitted. */
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setFields({});
    if (!seed) return;
    const f: Record<string, string> = {};
    let resolvedStart = "",
      resolvedEnd = "",
      cents = 0;
    try {
      resolvedStart = localToUtc(start, zone);
    } catch (e) {
      f["constraints.window_start"] = (e as Error).message;
    }
    try {
      resolvedEnd = localToUtc(end, zone);
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
      outcome_text: outcome.trim(),
      constraints: {
        ...seed.constraints,
        service,
        window_start: resolvedStart,
        window_end: resolvedEnd,
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
    try {
      if (mode === "live" && !canLive)
        throw new Error(
          "Live providers are not ready. Choose Demo or try again later.",
        );
      setBusy(true);
      const body = {
        ...parsed.data,
        outcome_text: `${outcome.trim()}\nAppointment window: ${boundaries} Approve exact terms before booking.`,
      };
      const view = await api.create(body);
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
          e.fields.length ? "Check the request details below." : e.message,
        );
      } else
        setError(
          e instanceof Error
            ? e.message
            : "Could not start your request. Try again.",
        );
    } finally {
      setBusy(false);
    }
  }
  function importJson() {
    try {
      fill(parseCreao(json, reference));
      setImported(true);
      setFields({});
      setError("");
    } catch {
      setError(
        "Check the imported JSON. It must include an outcome, valid constraints, and at least one provider.",
      );
    }
  }
  return (
    <main id="main" className="landing-main">
      {!revision && <LandingHero />}
      <section
        className="intake-section"
        id="intake"
        aria-labelledby="intake-title"
      >
        <div className="intake-heading">
          <h2 id="intake-title">
            {revision
              ? "Revise your request"
              : "What can we take off your list?"}
          </h2>
          <p>
            {revision
              ? "This creates a new request. Your original stays in Outcomes for reference."
              : "Try a dishwasher diagnostic visit. You approve the exact terms before booking."}
          </p>
        </div>
        <div className="intake-grid">
          <section
            className="card intake-card"
            aria-label="Create a repair coordination task"
          >
            {(error || Object.keys(fields).length > 0) && (
              <div
                ref={errorSummary}
                tabIndex={-1}
                className="error"
                role="alert"
              >
                <p>
                  {error || "Check the highlighted fields before continuing."}
                </p>
                {fields.constraints && <p>{fields.constraints}</p>}
              </div>
            )}
            {!seed ? (
              <div className="stack">
                <p className="empty">
                  {error
                    ? "Your request details are unavailable."
                    : "Loading request details…"}
                </p>
                {error && (
                  <button
                    className="button"
                    onClick={() => setAttempt((v) => v + 1)}
                  >
                    Try again
                  </button>
                )}
              </div>
            ) : (
              <form ref={form} onSubmit={submit} className="stack" noValidate>
                <div className="field">
                  <label htmlFor="outcome-input">What needs doing?</label>
                  <textarea
                    id="outcome-input"
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value)}
                    rows={3}
                    required
                    {...errorProps("outcome_text")}
                  />
                  <span className="field-note">
                    Add service details here. Scheduling and budget use the
                    fields below.
                  </span>
                  {fieldError("outcome_text")}
                </div>
                <div className="grid-two">
                  <label className="field">
                    Service category
                    <select
                      value={service}
                      onChange={(e) => setService(e.target.value)}
                      {...errorProps("constraints.service")}
                    >
                      <option value="dishwasher_repair">
                        Dishwasher repair
                      </option>
                      {service !== "dishwasher_repair" && (
                        <option value={service}>
                          {service.replaceAll("_", " ")}
                        </option>
                      )}
                    </select>
                    {fieldError("constraints.service")}
                  </label>
                  <label className="field">
                    Maximum visit charge (USD)
                    <div className="input-with-prefix">
                      <span className="input-prefix">$</span>
                      <input
                        inputMode="decimal"
                        value={budget}
                        onChange={(e) => setBudget(e.target.value)}
                        {...errorProps("constraints.max_visit_charge_cents")}
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
                      {...errorProps("constraints.window_start")}
                    />
                    {fieldError("constraints.window_start")}
                  </label>
                  <label className="field">
                    Window ends
                    <input
                      type="datetime-local"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                      {...errorProps("constraints.window_end")}
                    />
                    {fieldError("constraints.window_end")}
                  </label>
                </div>
                <p className="field-note">
                  All appointment times use {zone.replaceAll("_", " ")}. Parts
                  and labor are quoted after diagnosis.
                </p>
                <div>
                  <p className="field-title">Providers we’ll compare</p>
                  <div className="provider-pill-list">
                    {seed.providers.map((p) => (
                      <span key={p.id} className="provider-pill-item">
                        <span className="provider-initial">{p.name[0]}</span>
                        {p.name}
                      </span>
                    ))}
                  </div>
                  <p className="field-note">
                    {mode === "fixture"
                      ? "Two simulated providers are included in this demo."
                      : "Providers come from your connected intake."}
                  </p>
                  {fieldError("providers")}
                </div>
                <fieldset className="mode-toggle">
                  <legend>Run this request as</legend>
                  <label className="mode-btn">
                    <input
                      type="radio"
                      name="mode"
                      checked={mode === "fixture"}
                      onChange={() => setMode("fixture")}
                    />
                    Demo
                  </label>
                  <label className={`mode-btn ${!canLive ? "disabled" : ""}`}>
                    <input
                      type="radio"
                      name="mode"
                      checked={mode === "live"}
                      disabled={!canLive}
                      onChange={() => setMode("live")}
                    />
                    Live providers
                  </label>
                </fieldset>
                <p className="field-note">
                  {mode === "fixture"
                    ? "Demo messages, bookings, and evidence are simulated."
                    : "This request can contact the connected providers."}
                  {!canLive && " Live providers are not connected."}
                  {USE_MOCKS &&
                    " The offline demo supports the prefilled Tuesday window and $150 budget."}
                </p>
                <div className="request-summary" aria-live="polite">
                  <strong>Your time and budget</strong>
                  {boundaries}
                </div>
                <div className="permission-note">
                  <LockKeyhole size={16} />
                  <span>
                    You review the provider, visit charge, and cancellation
                    terms before booking.
                  </span>
                </div>
                {imported && (
                  <p className="notice">
                    <Check size={16} /> Workflow imported
                  </p>
                )}
                <button
                  className="button primary large submit-btn"
                  disabled={busy}
                >
                  {busy
                    ? "Starting coordination…"
                    : revision
                      ? "Start revised request"
                      : "Start coordinating"}
                  <ArrowRight size={18} />
                </button>
                {revision && (
                  <Link
                    className="text-link"
                    href={`/tasks/${encodeURIComponent(revision)}`}
                  >
                    Back to original request
                  </Link>
                )}
              </form>
            )}
          </section>
          <details className="card aside-import-card">
            <summary>
              Import from a workflow{" "}
              <span className="muted tiny">CREAO JSON</span>
            </summary>
            <div className="stack aside-import-body">
              <p className="field-note">
                Bring in an existing workflow’s outcome, boundaries, and
                providers.
              </p>
              <label className="field">
                Reference link
                <input
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  placeholder="Optional workflow reference"
                />
              </label>
              <label className="field">
                Task JSON
                <textarea
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                  className="mono"
                  rows={4}
                />
              </label>
              <button
                type="button"
                className="button"
                disabled={!json.trim()}
                onClick={importJson}
              >
                Apply imported request
              </button>
            </div>
          </details>
        </div>
      </section>
    </main>
  );
}
