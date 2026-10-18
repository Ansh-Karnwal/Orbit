import { Check, HelpCircle, ShieldCheck, X } from "lucide-react";
import { isComplete, localRange, money, safeWording } from "@/lib/format";
import { serviceName } from "@/lib/presentation";
import type { TaskView } from "@/lib/types";

export function VerificationPanel({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  const v = view.verification;
  const labels: Record<string, string> = {
    provider_identified: "Correct provider",
    service_matches: "Correct service",
    slot_within_window: "Appointment fits your window",
    charge_within_budget: "Charge stays within budget",
    fee_scope_clear: "Visit fee is clear",
    cancellation_terms_present: "Cancellation terms included",
    approval_matches_current_proposal: "Approval matches the current terms",
    confirmation_present: "Confirmation received",
    confirmation_consistent: "Confirmation matches your approval",
  };
  return (
    <section className="card verification-card">
      <div className="section-title">
        <div className="row">
          <ShieldCheck size={19} />
          <h2>Booking verification</h2>
        </div>
        <span
          className={`badge ${v?.verdict === "PASS" ? "green" : v?.verdict === "FAIL" ? "red" : "amber"}`}
        >
          {v?.verdict === "PASS"
            ? "Passed"
            : v?.verdict === "FAIL"
              ? "Failed"
              : "Pending"}
        </span>
      </div>
      {!v ? (
        <p className="empty">
          After you approve a proposal, we’ll check the booking confirmation
          against your exact terms.
        </p>
      ) : (
        <>
          <div className={`verdict ${v.verdict.toLowerCase()}`}>
            {v.verdict === "PASS"
              ? "Booking verified"
              : v.verdict === "FAIL"
                ? "Booking does not match what you approved — not complete"
                : "Confirmation evidence is still missing"}
          </div>
          <p className="verification-explanation">
            {safeWording(v.explanation, v.verdict)}
          </p>
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
                  <strong>{labels[p.name] ?? serviceName(p.name)}</strong>
                  <p>{safeWording(p.detail, v.verdict)}</p>
                  <div className="row wrap">
                    {[...new Set(p.evidence_ids)].map((id, n) => (
                      <button
                        className="text-link"
                        key={id}
                        onClick={() => onEvidence(id)}
                      >
                        View evidence
                        {p.evidence_ids.length > 1 ? ` ${n + 1}` : ""}
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
  const p = [...view.approvals]
    .reverse()
    .find((a) => a.status === "approved")?.proposal;
  const data = confirmation?.extracted;
  const provider =
    p?.provider_name ??
    view.providers.find((x) => x.id === data?.provider_id)?.name;
  const start =
    typeof data?.slot_start === "string" ? data.slot_start : p?.slot_start;
  const end = typeof data?.slot_end === "string" ? data.slot_end : p?.slot_end;
  const charge =
    typeof data?.visit_charge_cents === "number"
      ? data.visit_charge_cents
      : p?.visit_charge_cents;
  return (
    <section className="completion-card">
      <div className="row between completion-top">
        <div className="row">
          <span className="completion-check">
            <Check size={21} />
          </span>
          <h2>Handled ✓</h2>
        </div>
        <span className="badge green">Booking verified</span>
      </div>
      <dl className="receipt-grid">
        <div>
          <dt>Provider</dt>
          <dd>{provider ?? "See confirmation evidence"}</dd>
        </div>
        <div>
          <dt>Appointment</dt>
          <dd>
            {start && end
              ? localRange(start, end, view.task.constraints.timezone)
              : "See confirmation evidence"}
          </dd>
        </div>
        <div>
          <dt>Visit charge</dt>
          <dd>
            {charge !== undefined ? money(charge) : "See confirmation evidence"}
          </dd>
        </div>
      </dl>
      <p className="receipt-terms">
        <strong>Cancellation:</strong>{" "}
        {p?.cancellation_terms ?? "See your approved terms."}
      </p>
      <p className="receipt-note">
        Parts and labor are quoted after diagnosis.{" "}
        {view.task.mode === "fixture" ? "This is a simulated demo result." : ""}
      </p>
      <p className="receipt-note">
        <strong>Confirmation:</strong>{" "}
        {String(data?.confirmation_id ?? "See confirmation evidence")}
      </p>
    </section>
  );
}
