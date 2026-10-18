import { Check, HelpCircle, ShieldCheck, X } from "lucide-react";
import { isComplete, safeWording } from "@/lib/format";
import type { TaskView } from "@/lib/types";
export function VerificationPanel({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  const v = view.verification;
  return (
    <section className="card verification-card">
      <div className="section-title">
        <div className="row">
          <ShieldCheck size={18} />
          <h2>Independent verification</h2>
        </div>
        <span
          className={`badge ${v?.verdict === "PASS" ? "green" : v?.verdict === "FAIL" ? "red" : ""}`}
        >
          {v?.verdict ?? "PENDING"}
        </span>
      </div>
      {!v ? (
        <p className="empty">
          Verification pending on confirmation evidence.
        </p>
      ) : (
        <>
          <div className={`verdict ${v.verdict.toLowerCase()}`}>
            {v.verdict === "PASS"
              ? "Booking verified"
              : v.verdict === "FAIL"
                ? "Booking mismatch — rejected"
                : "Awaiting confirmation"}
          </div>
          <p className="verification-explanation">{safeWording(v.explanation, v.verdict)}</p>
          <ul className="predicates">
            {v.predicates.map((p, i) => (
              <li key={`${p.name}-${i}`}>
                {p.passed === true ? (
                  <Check size={16} aria-label="Passed" />
                ) : p.passed === false ? (
                  <X size={16} aria-label="Failed" />
                ) : (
                  <HelpCircle size={16} aria-label="Insufficient evidence" />
                )}
                <div>
                  <strong>{safeWording(p.name, v.verdict)}</strong>
                  <p>{safeWording(p.detail, v.verdict)}</p>
                  <div className="row wrap">
                    {p.evidence_ids.map((id) => (
                      <button
                        className="text-link"
                        key={id}
                        onClick={() => onEvidence(id)}
                      >
                        View evidence
                      </button>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
export function CompletionSummary({ view }: { view: TaskView }) {
  if (!isComplete(view)) return null;
  const confirmation = view.evidence.find(
    (e) => e.kind === "portal_confirmation",
  );
  return (
    <section className="completion-card">
      <div className="row between completion-top">
        <div className="row">
          <div className="completion-check">
            <Check size={22} />
          </div>
          <h2>Handled ✓</h2>
        </div>
        {view.task.mode === "fixture" && (
          <span className="badge">Fixture Result</span>
        )}
      </div>
      <p className="completion-summary-text">
        {view.task.summary ??
          "The independent verifier passed all required checks."}
      </p>
      <div className="completion-meta">
        <span className="mono confirmation-tag">
          Confirmation: {String(confirmation?.extracted.confirmation_id ?? "Verified")}
        </span>
      </div>
    </section>
  );
}
