"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  FileInput,
  LockKeyhole,
  Plus,
  X,
} from "lucide-react";
import { api, ApiError, MOCK_SERVICES } from "@/lib/api";
import { centsFromInput, localInput, localToUtc } from "@/lib/format";
import { parseCreao, taskCreateSchema } from "@/lib/intake";
import { providerAccent } from "@/lib/labels";
import { LandingHero } from "./LandingHero";
import type { Health, ProviderSpec, ServiceInfo, TaskCreate } from "@/lib/types";
const MAX_PROVIDERS = 10;
export default function Intake() {
  const router = useRouter();
  const [providers, setProviders] = useState<ProviderSpec[]>([]),
    [sandbox, setSandbox] = useState<ProviderSpec[]>([]),
    [services, setServices] = useState<ServiceInfo[]>(MOCK_SERVICES),
    [contact, setContact] = useState(""),
    [newName, setNewName] = useState(""),
    [newHandle, setNewHandle] = useState("");
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
    setProviders(value.providers);
    setContact(value.user_contact ?? "");
  }
  async function changeService(next: string) {
    setService(next);
    try {
      // Follow the seed's wording for the new service unless the outcome was edited.
      const s = await api.seed({ service: next });
      if (!seed || outcome === seed.outcome_text) setOutcome(s.outcome_text);
      setSeed((prev) => (prev ? { ...prev, outcome_text: s.outcome_text } : s));
    } catch {
      /* keep the current wording */
    }
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
    const id = `custom_${name.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`.slice(0, 40);
    addProvider({
      id,
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
    const wanted =
      typeof window !== "undefined"
        ? (new URLSearchParams(window.location.search).get("service") ?? undefined)
        : undefined;
    void Promise.all([api.seed({ service: wanted }), api.health()])
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
    void api
      .services()
      .then((s) => active && s.length && setServices(s))
      .catch(() => undefined);
    void api
      .sandboxProviders()
      .then((s) => active && setSandbox(s))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
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
                      onChange={(e) => void changeService(e.target.value)}
                    >
                      {services.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
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
                  <p className="field-title">
                    Candidate providers{" "}
                    <span className="muted">
                      ({providers.length}/{MAX_PROVIDERS})
                    </span>
                  </p>
                  <div className="provider-pill-list">
                    {providers.map((p, i) => (
                      <div key={p.id} className="provider-pill-item">
                        <span className={`provider-initial ${providerAccent(i)}`}>
                          {p.name.charAt(0)}
                        </span>
                        <span className="provider-name">{p.name}</span>
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
                      </div>
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
                  {fieldError("providers")}
                </div>
                <label className="field">
                  Text me updates at <span className="muted">(optional)</span>
                  <input
                    value={contact}
                    onChange={(e) => setContact(e.target.value)}
                    placeholder="fixture:you in the sandbox, or your phone for live"
                  />
                  {fieldError("user_contact")}
                </label>
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
