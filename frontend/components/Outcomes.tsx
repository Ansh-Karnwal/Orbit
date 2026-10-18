"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { localTimestamp, money } from "@/lib/format";
import { serviceName, statusLabels } from "@/lib/presentation";
import type { Task } from "@/lib/types";
export default function Outcomes() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void api
      .list()
      .then((value) => {
        if (active) {
          setTasks(value);
          setError("");
        }
      })
      .catch(() => {
        if (active) setError("We couldn’t load your outcomes. Try again.");
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  return (
    <main id="main" className="outcomes-main">
      <div className="row between outcomes-heading wrap">
        <div>
          <h1>Your outcomes</h1>
          <p>Pick up a request or look back at a previous result.</p>
        </div>
        <Link className="button primary" href="/#intake">
          <Plus size={16} />
          New outcome
        </Link>
      </div>
      {error ? (
        <div className="error" role="alert">
          <p>{error}</p>
          <button className="button" onClick={() => setAttempt((v) => v + 1)}>
            Try again
          </button>
        </div>
      ) : tasks === null ? (
        <p role="status">Loading your outcomes…</p>
      ) : !tasks.length ? (
        <section className="card stack">
          <h2>A little less chasing starts here.</h2>
          <p className="muted">
            Your requests and their progress will appear here.
          </p>
          <div>
            <Link className="button primary" href="/#intake">
              Create your first outcome <ArrowRight size={16} />
            </Link>
          </div>
        </section>
      ) : (
        <div className="outcome-list">
          {tasks
            .toSorted((a, b) => b.created_at.localeCompare(a.created_at))
            .map((task) => (
              <Link
                className="card"
                href={`/tasks/${encodeURIComponent(task.id)}`}
                key={task.id}
              >
                <div>
                  <h2>{serviceName(task.constraints.service)}</h2>
                  <p>{task.outcome_text}</p>
                  <p>
                    {money(task.constraints.max_visit_charge_cents)} maximum
                    visit charge ·{" "}
                    {localTimestamp(task.created_at, task.constraints.timezone)}
                  </p>
                </div>
                <span className="badge">
                  {statusLabels[task.status]} <ArrowRight size={14} />
                </span>
              </Link>
            ))}
        </div>
      )}
    </main>
  );
}
