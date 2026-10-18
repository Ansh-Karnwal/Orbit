import {
  Check,
  Clock3,
  ExternalLink,
  Star,
  TriangleAlert,
  X,
} from "lucide-react";
import { localRange, money, safeWording } from "@/lib/format";
import { providerAccent } from "@/lib/labels";
import type { ContextFact, ProviderSpec, TaskView } from "@/lib/types";
function factValue(fact: ContextFact, tz: string): string {
  if (fact.key.endsWith("_cents") && typeof fact.value === "number")
    return money(fact.value);
  if (fact.key.endsWith("slots_offered") || fact.key.endsWith("portal_slots")) {
    if (Array.isArray(fact.value))
      return fact.value.length
        ? fact.value
            .map((s: unknown) => {
              if (
                s &&
                typeof s === "object" &&
                "start" in s &&
                "end" in s &&
                typeof s.start === "string" &&
                typeof s.end === "string"
              )
                return localRange(s.start, s.end, tz);
              return "Slot data unavailable";
            })
            .join("\n")
        : "No open appointments";
  }
  if (fact.key.endsWith("repair_cost_known"))
    return fact.value === true
      ? "Repair cost provided"
      : "Parts & labor unknown until diagnosis";
  if (typeof fact.value === "boolean") return fact.value ? "Yes" : "No";
  if (typeof fact.value === "string") return fact.value.replaceAll("_", " ");
  if (Array.isArray(fact.value) && fact.key.endsWith("extra_fees"))
    return fact.value
      .map((v: unknown) =>
        v &&
        typeof v === "object" &&
        "name" in v &&
        "cents" in v &&
        typeof v.cents === "number"
          ? `${v.name}: ${money(v.cents)}`
          : "Unspecified fee",
      )
      .join(", ");
  return JSON.stringify(fact.value);
}
export function FactHistory({
  facts,
  timezone,
  verdict,
  onEvidence,
}: {
  facts: ContextFact[];
  timezone: string;
  verdict?: TaskView["verification"];
  onEvidence: (id: string) => void;
}) {
  return (
    <div className="fact-history">
      {[...facts]
        .sort((a, b) => a.version - b.version)
        .map((f) => (
          <div
            key={f.id}
            className={f.status === "superseded" ? "old-fact" : "current-fact"}
          >
            <button
              className="fact-value"
              onClick={() => onEvidence(f.source_id)}
              title={`View source ${f.source_id}`}
            >
              {f.status === "superseded" ? (
                <del>
                  {safeWording(factValue(f, timezone), verdict?.verdict)}
                </del>
              ) : (
                safeWording(factValue(f, timezone), verdict?.verdict)
              )}
              <ExternalLink size={11} />
            </button>
            {f.status === "superseded" && (
              <span className="superseded-tag">Superseded</span>
            )}
          </div>
        ))}
    </div>
  );
}
export function ProviderCard({
  provider,
  view,
  onEvidence,
  accent,
  proposed = false,
}: {
  provider: ProviderSpec;
  view: TaskView;
  onEvidence: (id: string) => void;
  accent?: number;
  proposed?: boolean;
}) {
  const facts = view.facts.filter((f) => f.key.startsWith(`${provider.id}.`)),
    reasons = view.eligibility[provider.id],
    replied = facts.some(
      (f) =>
        !f.key.endsWith(".declined_by_user") &&
        !f.key.endsWith(".declined_slots"),
    ),
    known =
      !!reasons &&
      facts.some((f) => f.key === `${provider.id}.visit_charge_cents`),
    eligible = known && reasons.length === 0,
    summary = view.provider_summaries?.[provider.id],
    chosen =
      proposed &&
      view.approvals.some(
        (a) => a.status === "approved" && a.proposal.provider_id === provider.id,
      ),
    index = accent ?? view.providers.findIndex((p) => p.id === provider.id);
  // Declined if the user rejected their proposal — unless the user has since reconsidered
  // (eligibility then no longer says "declined by you").
  const declinedReason = !!reasons?.some((r) => /declined by you/i.test(r));
  const declined =
    declinedReason ||
    (!proposed &&
      reasons !== undefined &&
      reasons.length > 0 &&
      view.approvals.some(
        (a) => a.proposal.provider_id === provider.id && a.status === "rejected",
      ));
  const visitChargeFacts = facts.filter(
    (f) => f.key === `${provider.id}.visit_charge_cents`,
  );
  const fields = [
    ["fee_scope", "Includes"],
    ["slots_offered", "Provider offered"],
    ["portal_slots", "Portal availability"],
    ["cancellation_terms", "Cancellation"],
  ];
  return (
    <article
      className={`card provider-card ${reasons?.some((r) => /budget/i.test(r)) ? "over-budget" : ""} ${proposed ? "proposed" : ""} ${declined ? "declined" : ""}`}
    >
      <div className="row between provider-header">
        <div className="row provider-identity">
          <span className={`provider-initial ${providerAccent(Math.max(index, 0))}`}>
            {provider.name.charAt(0)}
          </span>
          <div>
            <h3>{provider.name}</h3>
          </div>
        </div>
        <span
          className={`badge ${proposed ? "blue" : declined ? "" : eligible ? "green" : known ? "amber" : ""}`}
        >
          {proposed ? (
            <Star size={13} />
          ) : declined ? (
            <X size={13} />
          ) : eligible ? (
            <Check size={13} />
          ) : known ? (
            <TriangleAlert size={13} />
          ) : (
            <Clock3 size={13} />
          )}{" "}
          {proposed
            ? chosen
              ? "Chosen"
              : "Proposed"
            : declined
              ? "Declined"
              : eligible
                ? "Fits your request"
                : known
                  ? "Unavailable"
                  : "Checking"}
        </span>
      </div>
      {summary && (
        <p className="provider-summary">
          {safeWording(summary, view.verification?.verdict)}
        </p>
      )}

      {visitChargeFacts.length > 0 && (
        <div className="provider-pricing-highlight">
          <span className="pricing-label">Visit charge</span>
          <FactHistory
            facts={visitChargeFacts}
            timezone={view.task.constraints.timezone}
            verdict={view.verification}
            onEvidence={onEvidence}
          />
        </div>
      )}

      {known && reasons && reasons.length > 0 && (
        <div className="reasons-banner">
          {reasons.map((r) => (
            <span key={r} className="reason-item">
              <TriangleAlert size={13} />
              {safeWording(r, view.verification?.verdict)}
            </span>
          ))}
        </div>
      )}

      {!replied ? (
        <p className="empty">Awaiting provider response…</p>
      ) : (
        <dl className="provider-facts">
          {fields.map(([key, label]) => {
            const versions = facts.filter(
              (f) => f.key === `${provider.id}.${key}`,
            );
            if (!versions.length) return null;
            return (
              <div key={key}>
                <dt>{label}</dt>
                <dd>
                  <FactHistory
                    facts={versions}
                    timezone={view.task.constraints.timezone}
                    verdict={view.verification}
                    onEvidence={onEvidence}
                  />
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      <p className="provider-footnote">
        Parts and labor are quoted after diagnosis.
      </p>
    </article>
  );
}
