"use client";
import { useEffect, useRef } from "react";
import {
  Check,
  Circle,
  GitBranch,
  LoaderCircle,
  MessageSquare,
  Minus,
  TriangleAlert,
  ShieldCheck,
} from "lucide-react";
import { localTime, safeWording } from "@/lib/format";
import type { TaskView } from "@/lib/types";
const names: Record<string, string> = {
  send_inquiry: "Contact providers",
  await_reply: "Collect replies",
  extract_quote: "Extract sourced facts",
  compare_quotes: "Compare against constraints",
  read_availability: "Check portal availability",
  request_approval: "Request your approval",
  submit_booking: "Submit booking request",
  reconcile_booking: "Check existing booking",
  verify: "Verify the result",
  summarize: "Prepare outcome summary",
};
export function Plan({ view }: { view: TaskView }) {
  return (
    <section className="card">
      <div className="section-title">
        <div className="row">
          <GitBranch size={18} />
          <h2>The plan</h2>
        </div>
        <span className="tiny muted">{view.steps.length} steps</span>
      </div>
      {[...new Set(view.steps.map((s) => s.plan_version))]
        .sort((a, b) => a - b)
        .map((version) => (
          <div key={version} className="plan-version">
            <p className="eyebrow">PLAN V{version}</p>
            {view.timeline
              .filter(
                (e) =>
                  e.type === "plan.revised" && e.data.plan_version === version,
              )
              .map((e) => (
                <p className="plan-revision" key={e.id}>
                  {safeWording(e.message, view.verification?.verdict)}
                </p>
              ))}
            <ol className="steps">
              {view.steps
                .filter((s) => s.plan_version === version)
                .map((s) => (
                  <li key={s.id} className={`step ${s.state}`}>
                    <span className="step-icon">
                      {s.state === "succeeded" ? (
                        <Check size={14} />
                      ) : s.state === "running" ? (
                        <LoaderCircle className="spin" size={14} />
                      ) : s.state === "skipped" ? (
                        <Minus size={14} />
                      ) : s.state === "failed" || s.state === "blocked" ? (
                        <TriangleAlert size={14} />
                      ) : (
                        <Circle size={10} />
                      )}
                    </span>
                    <div>
                      <span>{names[s.kind]}</span>
                      {s.provider_id && (
                        <small>
                          {view.providers.find((p) => p.id === s.provider_id)
                            ?.name ?? s.provider_id}
                        </small>
                      )}
                      {s.error && (
                        <small className="field-error">
                          {safeWording(s.error, view.verification?.verdict)}
                        </small>
                      )}
                    </div>
                    <span className="tiny muted">{s.state}</span>
                  </li>
                ))}
            </ol>
          </div>
        ))}
    </section>
  );
}
export function Timeline({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null),
    follow = useRef(true);
  useEffect(() => {
    if (follow.current && container.current)
      container.current.scrollTop = container.current.scrollHeight;
  }, [view.timeline.length]);
  return (
    <section className="card">
      <div className="section-title">
        <h2>Activity timeline</h2>
        <span className="tiny muted">{view.task.constraints.timezone}</span>
      </div>
      <div
        className="timeline"
        ref={container}
        role="log"
        aria-label="Task activity"
        onScroll={() => {
          const el = container.current;
          if (el)
            follow.current =
              el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        }}
      >
        {view.timeline.map((e) => {
          const highlighted = [
            "conflict.detected",
            "approval.invalidated",
            "plan.revised",
            "booking.ambiguous",
            "verification.completed",
            "message.duplicate_ignored",
          ].includes(e.type);
          return (
            <div
              key={e.id}
              className={`timeline-event ${highlighted ? "highlighted" : ""} ${e.type === "verification.completed" ? "verification-event" : ""}`}
            >
              <span className="timeline-icon">
                {e.type === "verification.completed" ? (
                  <ShieldCheck size={14} />
                ) : e.type === "plan.revised" ? (
                  <GitBranch size={14} />
                ) : highlighted ? (
                  <TriangleAlert size={14} />
                ) : (
                  <MessageSquare size={14} />
                )}
              </span>
              <div>
                <p>{safeWording(e.message, view.verification?.verdict)}</p>
                <span className="tiny muted">
                  {localTime(e.at, view.task.constraints.timezone)} ·{" "}
                  {e.type.replaceAll(".", " / ").replaceAll("_", " ")}
                </span>
                {typeof e.data.evidence_id === "string" && (
                  <button
                    className="text-link"
                    onClick={() => onEvidence(String(e.data.evidence_id))}
                  >
                    View source
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
