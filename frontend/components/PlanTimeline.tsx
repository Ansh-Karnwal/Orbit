"use client";
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
import { localTimestamp, safeWording } from "@/lib/format";
import type { TaskView, TimelineEvent } from "@/lib/types";
const names: Record<string, string> = {
  send_inquiry: "Contact providers",
  await_reply: "Collect replies",
  extract_quote: "Read provider terms",
  compare_quotes: "Compare your options",
  read_availability: "Check available appointments",
  request_approval: "Get your approval",
  confirm_with_provider: "Provider confirms",
  submit_booking: "Submit booking request",
  reconcile_booking: "Check existing booking",
  verify: "Verify the result",
  summarize: "Prepare your receipt",
};
export function Plan({ view }: { view: TaskView }) {
  const versions = [...new Set(view.steps.map((s) => s.plan_version))].sort(
    (a, b) => b - a,
  );
  function versionContent(version: number) {
    return (
      <div className="plan-version">
        <p className="eyebrow">Plan {version}</p>
        {view.timeline
          .filter(
            (e) => e.type === "plan.revised" && e.data.plan_version === version,
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
                  ) : ["failed", "blocked"].includes(s.state) ? (
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
                <span className="tiny muted">
                  {
                    {
                      succeeded: "Done",
                      running: "In progress",
                      ready: "Up next",
                      pending: "Waiting",
                      skipped: "Skipped",
                      failed: "Needs attention",
                      blocked: "Paused",
                    }[s.state]
                  }
                </span>
              </li>
            ))}
        </ol>
      </div>
    );
  }
  return (
    <section className="card">
      <div className="section-title">
        <div className="row">
          <GitBranch size={18} />
          <h2>The plan</h2>
        </div>
        <span className="badge">
          {versions.length ? `Revision ${versions[0]}` : "Preparing"}
        </span>
      </div>
      {versions.length ? (
        <>
          {versionContent(versions[0])}
          {versions.slice(1).map((version) => (
            <details className="disclosure" key={version}>
              <summary>Earlier plan · revision {version}</summary>
              {versionContent(version)}
            </details>
          ))}
        </>
      ) : (
        <p className="empty">
          Your coordination steps will appear here shortly.
        </p>
      )}
    </section>
  );
}
const milestones = new Set([
  "task.created",
  "message.sent",
  "message.received",
  "message.duplicate_ignored",
  "plan.revised",
  "provider.disqualified",
  "approval.requested",
  "approval.invalidated",
  "approval.decided",
  "booking.submitted",
  "booking.ambiguous",
  "booking.reconciled",
  "verification.completed",
  "task.completed",
  "question.asked",
  "fact.superseded",
]);
export function Timeline({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  function eventRow(e: TimelineEvent, technical = false) {
    return (
      <div key={e.id} className="timeline-event">
        <span className="timeline-icon">
          {e.type === "verification.completed" ? (
            <ShieldCheck size={17} />
          ) : e.type === "plan.revised" ? (
            <GitBranch size={17} />
          ) : (
            <MessageSquare size={17} />
          )}
        </span>
        <div>
          <p>{safeWording(e.message, view.verification?.verdict)}</p>
          <span className="tiny muted">
            {localTimestamp(e.at, view.task.constraints.timezone)}
            {technical
              ? ` · ${e.type.replaceAll(".", " / ").replaceAll("_", " ")}`
              : ""}
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
  }
  const events = view.timeline
    .filter((e) => milestones.has(e.type))
    .toReversed();
  return (
    <section className="card">
      <div className="section-title">
        <div>
          <h2>Activity timeline</h2>
          <p className="field-note">Meaningful updates, most recent first.</p>
        </div>
      </div>
      <div className="timeline" role="log" aria-label="Task activity">
        {events.length ? (
          events.map((e) => eventRow(e))
        ) : (
          <p className="empty">
            Updates will appear as coordination progresses.
          </p>
        )}
      </div>
      <details className="disclosure">
        <summary>
          Technical event log{" "}
          <span className="badge">{view.timeline.length} events</span>
        </summary>
        <div className="technical-log">
          {view.timeline.toReversed().map((e) => eventRow(e, true))}
        </div>
      </details>
    </section>
  );
}
