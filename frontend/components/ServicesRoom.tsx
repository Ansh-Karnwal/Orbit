"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Plus, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { localTimestamp } from "@/lib/format";
import { REASON_LABELS, serviceLabel } from "@/lib/labels";
import type { ServiceInfo, Task, TaskStatus, UserInfo } from "@/lib/types";

const GROUPS: { id: string; label: string; statuses: TaskStatus[] }[] = [
  { id: "approval", label: "Needs your approval", statuses: ["AWAITING_APPROVAL"] },
  { id: "blocked", label: "Needs your input", statuses: ["BLOCKED"] },
  {
    id: "working",
    label: "Orbit is working on it",
    statuses: ["DRAFT", "PLANNING", "RUNNING", "WAITING_EXTERNAL", "VERIFYING"],
  },
  { id: "handled", label: "Handled", statuses: ["COMPLETED"] },
  { id: "closed", label: "Closed", statuses: ["CANCELLED", "FAILED"] },
];

/** One place to see every search, for every service (roadmap D). */
export default function ServicesRoom() {
  const [services, setServices] = useState<ServiceInfo[]>([]),
    [tasks, setTasks] = useState<Task[] | null>(null),
    [user, setUser] = useState<UserInfo | null>(null),
    [filter, setFilter] = useState<string>(""),
    [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([api.services(), api.list(), api.me()])
      .then(([s, t, u]) => {
        if (!active) return;
        setServices(s);
        setTasks(t);
        setUser(u);
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : "Could not load"));
    return () => {
      active = false;
    };
  }, []);

  const shown = useMemo(
    () => (tasks ?? []).filter((t) => !filter || t.constraints.service === filter),
    [tasks, filter],
  );
  const counts = useMemo(() => {
    const c = new Map<string, number>();
    for (const t of tasks ?? [])
      c.set(t.constraints.service, (c.get(t.constraints.service) ?? 0) + 1);
    return c;
  }, [tasks]);

  return (
    <main id="main" className="services-main">
      <div className="section-title services-heading">
        <div>
          <h1>Services</h1>
          <p className="muted">
            Everything Orbit can coordinate, and every search you&apos;ve started
            {user?.authenticated ? ` as ${user.display_name}` : ""}.
          </p>
        </div>
        <Link className="button primary" href="/#intake">
          <Plus size={15} />
          New search
        </Link>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <section aria-labelledby="catalog-title" className="stack">
        <h2 id="catalog-title">What Orbit can arrange</h2>
        <div className="service-grid">
          {services.map((s) => (
            <article key={s.id} className="card service-card">
              <span className="float-icon blue">
                <Wrench size={18} />
              </span>
              <h3>{s.label}</h3>
              <p className="muted">{s.description}</p>
              <p className="service-meta">
                {counts.get(s.id) ?? 0} search{(counts.get(s.id) ?? 0) === 1 ? "" : "es"} ·{" "}
                <span className="mono">{s.pack}</span>
              </p>
              <Link className="button small" href={`/?service=${encodeURIComponent(s.id)}#intake`}>
                Start a {s.label.toLowerCase()} search
                <ArrowRight size={14} />
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="searches-title" className="stack">
        <div className="row between wrap">
          <h2 id="searches-title">Your searches</h2>
          <div className="row wrap service-filters" role="group" aria-label="Filter by service">
            <button
              className={`chip ${filter === "" ? "active" : ""}`}
              aria-pressed={filter === ""}
              onClick={() => setFilter("")}
            >
              All
            </button>
            {services.map((s) => (
              <button
                key={s.id}
                className={`chip ${filter === s.id ? "active" : ""}`}
                aria-pressed={filter === s.id}
                onClick={() => setFilter(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
        {tasks === null ? (
          <p className="empty">Loading your searches…</p>
        ) : shown.length === 0 ? (
          <p className="empty">
            No searches yet{filter ? ` for ${serviceLabel(filter).toLowerCase()}` : ""}.
          </p>
        ) : (
          GROUPS.map((g) => {
            const items = shown.filter((t) => g.statuses.includes(t.status));
            if (!items.length) return null;
            return (
              <div key={g.id} className="search-group">
                <h3>
                  {g.label} <span className="muted">({items.length})</span>
                </h3>
                <ul className="search-list">
                  {items.map((t) => (
                    <li key={t.id}>
                      <Link href={`/tasks/${encodeURIComponent(t.id)}`} className="search-row">
                        <span className="search-service">
                          {serviceLabel(t.constraints.service)}
                        </span>
                        <span className="search-outcome">{t.outcome_text}</span>
                        <span className={`badge ${t.status === "BLOCKED" ? "amber" : ""}`}>
                          {t.status === "BLOCKED" && t.reason_code
                            ? REASON_LABELS[t.reason_code]
                            : t.status.replaceAll("_", " ").toLowerCase()}
                        </span>
                        <span className="muted search-time">
                          {localTimestamp(t.created_at, t.constraints.timezone)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })
        )}
      </section>
    </main>
  );
}
