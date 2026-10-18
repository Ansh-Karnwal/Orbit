"use client";
import { useState } from "react";
import { CalendarClock, Check, LockKeyhole, Octagon, X } from "lucide-react";
import { api, StaleProposalError } from "@/lib/api";
import { localRange, money, safeWording } from "@/lib/format";
import type { Approval, Verdict } from "@/lib/types";
export function ApprovalCard({
  approval,
  timezone,
  verdict,
  onRefresh,
  disabled = false,
}: {
  approval: Approval;
  timezone: string;
  verdict?: Verdict;
  onRefresh: () => Promise<void>;
  disabled?: boolean;
}) {
  const [posting, setPosting] = useState(false),
    [error, setError] = useState("");
  const p = approval.proposal,
    invalid = approval.status === "invalidated",
    pending = approval.status === "requested";
  async function decide(
    decision: "approved" | "rejected",
    scope: "provider" | "proposal" = "provider",
  ) {
    setPosting(true);
    setError("");
    try {
      await api.approve(approval.task_id, {
        proposal_hash: approval.proposal_hash,
        decision,
        approver: "demo_user", // ignored by the backend: the signed-in user decides
        ...(decision === "rejected" ? { scope } : {}),
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
  async function stop() {
    setPosting(true);
    setError("");
    try {
      await api.cancel(approval.task_id);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to stop the task");
    } finally {
      setPosting(false);
    }
  }
  const declined = approval.status === "rejected";
  return (
    <section
      className={`card approval-card ${invalid ? "invalid" : ""} ${declined ? "declined" : ""}`}
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
                : declined
                  ? "You declined this"
                  : "Your decision"}
          </h2>
        </div>
        <span className={`badge ${pending ? "amber" : ""}`}>
          {declined ? "declined" : approval.status}
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
      <div className="row between approval-provider">
        <div>
          <h3>{p.provider_name}</h3>
          <p className="approval-service-tag">{p.service.replaceAll("_", " ")}</p>
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
      </dl>
      <div className="row between wrap approval-footer">
        <span className="approval-security-note">Binding agreement hash</span>
        <abbr className="mono tiny hash" title={approval.proposal_hash}>
          #{approval.proposal_hash.slice(0, 8)}
        </abbr>
      </div>
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
            onClick={() => void decide("rejected", "provider")}
            title="Decline this provider; Orbit looks for the next option and asks you again"
          >
            <X size={16} />
            Not this one — find another
          </button>
          <div className="approval-secondary row">
            <button
              className="text-button"
              disabled={posting || disabled}
              onClick={() => void decide("rejected", "proposal")}
              title="Keep this provider but decline this time; Orbit offers their next time if they have one"
            >
              <CalendarClock size={14} />A different time
            </button>
            <button
              className="text-button danger"
              disabled={posting || disabled}
              onClick={() => void stop()}
              title="Cancel this task; nothing is booked"
            >
              <Octagon size={14} />
              Stop here
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
