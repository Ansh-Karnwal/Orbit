"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Check, LockKeyhole, Plus, X } from "lucide-react";
import { api, ApiError, MOCK_SERVICES, USE_MOCKS } from "@/lib/api";
import { providerAccent, serviceLabel } from "@/lib/labels";
import {
  centsFromInput,
  localInput,
  localRange,
  localToUtc,
  money,
} from "@/lib/format";
import { parseCreao, taskCreateSchema } from "@/lib/intake";
import { LandingHero } from "./LandingHero";
import type { Health, ProviderSpec, ServiceInfo, TaskCreate } from "@/lib/types";

const MAX_PROVIDERS = 10;
const defaultOutcome = (service: string) =>
  `Arrange a ${serviceLabel(service).toLowerCase().replace(/ repair$/, "")} diagnostic visit. Ask me before booking.`;

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
  const [providers, setProviders] = useState<ProviderSpec[]>([]);
  const [sandbox, setSandbox] = useState<ProviderSpec[]>([]);
  const [services, setServices] = useState<ServiceInfo[]>(MOCK_SERVICES);
  const [contact, setContact] = useState("");
  const [newName, setNewName] = useState("");
  const [newHandle, setNewHandle] = useState("");
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
    setProviders(value.providers);
    setContact(value.user_contact ?? "");
  }
  function changeService(next: string) {
    // Keep the person's own wording; only swap our default sentence.
    if (outcome.trim() === defaultOutcome(service)) setOutcome(defaultOutcome(next));
    setService(next);
  }
  function addProvider(p: ProviderSpec) {
    setProviders((cur) =>
      cur.length >= MAX_PROVIDERS || cur.some((x) => x.id === p.id)
        ? cur
        : [...cur, p],
    );
  }
  function addCustomProvider() {
    const name = newName.trim(),
      handle = newHandle.trim();
    if (!name || !handle) return;
    addProvider({
      id: `custom_${name.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`.slice(0, 40),
      name,
      handle,
      channel: handle.startsWith("fixture:") ? "fixture" : "imessage",
      portal_url: null,
    });
    setNewName("");
    setNewHandle("");
  }
  useEffect(() => {
    let active = true;
    void api
      .services()
      .then((s) => active && s.length > 0 && setServices(s))
      .catch(() => undefined);
    void api
      .sandboxProviders()
      .then((s) => active && setSandbox(s))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams(window.location.search);
    const revise = params.get("revise");
    const wanted = params.get("service") ?? undefined; // from the Services room
    void Promise.all([
      api.seed({ service: wanted }),
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
            outcome_text: defaultOutcome(s.constraints.service),
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
    providers.length > 0 &&
    providers.every(
      (p) => p.channel !== "fixture" && !p.handle.startsWith("fixture:"),
    );
  const addable = sandbox.filter((p) => !providers.some((x) => x.id === p.id));
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
      providers,
      user_contact: contact.trim() || null,
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
                      onChange={(e) => changeService(e.target.value)}
                      {...errorProps("constraints.service")}
                    >
                      {services.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                      {!services.some((s) => s.id === service) && (
                        <option value={service}>{serviceLabel(service)}</option>
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
                  <p className="field-title">
                    Providers we’ll compare{" "}
                    <span className="muted">
                      ({providers.length}/{MAX_PROVIDERS})
                    </span>
                  </p>
                  <div className="provider-pill-list">
                    {providers.map((p, i) => (
                      <span key={p.id} className="provider-pill-item">
                        <span className={`provider-initial ${providerAccent(i)}`}>
                          {p.name[0]}
                        </span>
                        {p.name}
                        <button
                          type="button"
                          className="pill-remove"
                          aria-label={`Remove ${p.name}`}
                          disabled={providers.length <= 1}
                          onClick={() =>
                            setProviders((cur) => cur.filter((x) => x.id !== p.id))
                          }
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                  </div>
                  {providers.length < MAX_PROVIDERS && (
                    <div className="provider-add stack">
                      {addable.length > 0 && (
                        <div className="row wrap">
                          {addable.map((p) => (
                            <button
                              key={p.id}
                              type="button"
                              className="button small"
                              onClick={() => addProvider(p)}
                            >
                              <Plus size={13} />
                              {p.name}
                              <span className="muted"> (sandbox)</span>
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="row wrap provider-custom">
                        <input
                          aria-label="New provider name"
                          placeholder="Provider name"
                          value={newName}
                          onChange={(e) => setNewName(e.target.value)}
                        />
                        <input
                          aria-label="New provider handle"
                          placeholder="Handle (fixture:id or phone)"
                          value={newHandle}
                          onChange={(e) => setNewHandle(e.target.value)}
                        />
                        <button
                          type="button"
                          className="button small"
                          disabled={!newName.trim() || !newHandle.trim()}
                          onClick={addCustomProvider}
                        >
                          <Plus size={13} />
                          Add
                        </button>
                      </div>
                    </div>
                  )}
                  <p className="field-note">
                    {mode === "fixture"
                      ? "Simulated providers reply in the demo; add Coastal to compare three."
                      : "Providers come from your connected intake."}
                  </p>
                  {fieldError("providers")}
                </div>
                <label className="field">
                  Text me updates at <span className="muted">(optional)</span>
                  <input
                    value={contact}
                    onChange={(e) => setContact(e.target.value)}
                    placeholder="fixture:you in the demo, or your phone for live"
                    {...errorProps("user_contact")}
                  />
                  {fieldError("user_contact")}
                </label>
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
