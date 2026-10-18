"use client";
import { useState } from "react";
import { Check, LockKeyhole, X } from "lucide-react";
import { api, StaleProposalError } from "@/lib/api";
import { localRange, money, safeWording } from "@/lib/format";
import type { Approval, Verdict } from "@/lib/types";
export function ApprovalCard({
  approval,
  timezone,
  verdict,
  onRefresh,
  disabled = false,
  budget,
}: {
  approval: Approval;
  timezone: string;
  verdict?: Verdict;
  onRefresh: () => Promise<void>;
  disabled?: boolean;
  budget?: number;
}) {
  const [posting, setPosting] = useState(false),
    [error, setError] = useState("");
  const p = approval.proposal,
    invalid = approval.status === "invalidated",
    pending = approval.status === "requested";
  async function decide(decision: "approved" | "rejected") {
    setPosting(true);
    setError("");
    try {
      await api.approve(approval.task_id, {
        proposal_hash: approval.proposal_hash,
        decision,
        approver: "demo_user",
      });
      await onRefresh();
    } catch (e) {
      setError(
        e instanceof StaleProposalError
          ? "Terms changed since you opened this — review the new proposal."
          : e instanceof Error
            ? e.message
            : "Unable to send decision",
      );
      if (e instanceof StaleProposalError) {
        try {
          await onRefresh();
        } catch {
          /* The decision error remains visible. */
        }
      }
    } finally {
      setPosting(false);
    }
  }
  return (
    <section
      className={`card approval-card ${invalid ? "invalid" : ""}`}
      aria-label={`${p.provider_name} approval`}
    >
      <div className="section-title">
        <div className="row">
          <LockKeyhole size={18} />
          <h2>
            {invalid
              ? "Previous approval withdrawn"
              : pending
                ? "A decision for you"
                : "Your decision"}
          </h2>
        </div>
        <span className={`badge ${pending ? "amber" : ""}`}>
          {
            {
              requested: "Awaiting you",
              approved: "Approved",
              rejected: "Declined",
              invalidated: "Withdrawn",
              expired: "Expired",
            }[approval.status]
          }
        </span>
      </div>
      {invalid && (
        <p className="withdrawal">
          {safeWording(
            approval.invalidated_reason ?? "The proposal terms changed.",
            verdict,
          )}
        </p>
      )}
      {pending && budget !== undefined && (
        <p className="recommendation">
          <strong>Recommended.</strong>{" "}
          {budget >= p.visit_charge_cents
            ? `${money(budget - p.visit_charge_cents)} below your visit budget.`
            : `${money(p.visit_charge_cents - budget)} above your visit budget.`}{" "}
        </p>
      )}
      <div className="row between approval-provider">
        <div>
          <h3>{p.provider_name}</h3>
          <p className="approval-service-tag">
            {p.service.replaceAll("_", " ")}
          </p>
        </div>
        <div className="approval-price-box">
          <span className="approval-price-label">Visit Charge</span>
          <strong className="approval-price">
            {money(p.visit_charge_cents)}
          </strong>
        </div>
      </div>
      <dl className="terms">
        <div>
          <dt>Appointment</dt>
          <dd>{localRange(p.slot_start, p.slot_end, timezone)}</dd>
        </div>
        <div>
          <dt>Includes</dt>
          <dd>
            {p.fee_scope === "diagnostic_visit_including_travel"
              ? "Diagnostic visit incl. travel"
              : safeWording(p.fee_scope.replaceAll("_", " "), verdict)}
          </dd>
        </div>
        <div>
          <dt>Cancellation</dt>
          <dd>{safeWording(p.cancellation_terms, verdict)}</dd>
        </div>
        <div>
          <dt>Repair costs</dt>
          <dd>
            {p.repair_cost_known
              ? "Review the provider’s repair quote separately."
              : "Parts and labor quoted after diagnosis; this charge covers the visit only."}
          </dd>
        </div>
      </dl>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {pending && (
        <div className="approval-buttons">
          <button
            className="button primary large approve-btn"
            disabled={posting || disabled}
            onClick={() => void decide("approved")}
          >
            <Check size={18} />
            {posting ? "Sending decision…" : "Approve these terms"}
          </button>
          <button
            className="button reject-btn"
            disabled={posting || disabled}
            onClick={() => void decide("rejected")}
          >
            <X size={16} />
            Reject
          </button>
        </div>
      )}
      {pending && (
        <p className="decision-note">
          After approval, Orbit submits the request and checks the confirmation
          against these exact terms.
        </p>
      )}
      <details className="approval-footer">
        <summary>Approval reference</summary>
        <p>This reference binds your decision to the terms shown above.</p>
        <span className="mono hash">{approval.proposal_hash}</span>
      </details>
    </section>
  );
}
