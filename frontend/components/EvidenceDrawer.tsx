"use client";
/* eslint-disable @next/next/no-img-element -- Artifact URLs require a native, unoptimized evidence preview. */
import { useEffect, useRef } from "react";
import { ExternalLink, FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import {
  claimLabel,
  localTimestamp,
  localTime,
  money,
  safeWording,
} from "@/lib/format";
import type { EvidenceArtifact, Verdict } from "@/lib/types";
const labels: Record<string, string> = {
  message_in: "Provider message",
  message_out: "Outgoing message",
  portal_confirmation: "Portal record",
  browser_trace: "Browser trace",
  screenshot: "Screenshot",
  availability: "Availability",
  delivery_receipt: "Delivery receipt",
  creao_output: "CREAO output",
};
export function EvidenceList({
  evidence,
  timezone,
  verdict,
  onEvidence,
}: {
  evidence: EvidenceArtifact[];
  timezone: string;
  verdict?: Verdict;
  onEvidence: (id: string) => void;
}) {
  return (
    <section className="card">
      <div className="section-title">
        <h2>Evidence library</h2>
        <span className="badge">{evidence.length} artifacts</span>
      </div>
      {!evidence.length && (
        <p className="empty">
          Sources will appear here as the task progresses.
        </p>
      )}
      <div className="evidence-list">
        {evidence.map((e) => (
          <button key={e.id} onClick={() => onEvidence(e.id)}>
            <FileText size={18} />
            <div>
              <strong>{labels[e.kind]}</strong>
              <p>
                {claimLabel(e.claim_level, verdict)} ·{" "}
                {e.source.replaceAll("_", " ")}
              </p>
              <p>{localTime(e.captured_at, timezone)}</p>
            </div>
            {e.is_fixture && <span className="badge amber">Fixture</span>}
            <ExternalLink size={13} />
          </button>
        ))}
      </div>
    </section>
  );
}
export function EvidenceDrawer({
  id,
  evidence,
  timezone,
  verdict,
  onClose,
}: {
  id: string | null;
  evidence: EvidenceArtifact[];
  timezone: string;
  verdict?: Verdict;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const e = evidence.find((e) => e.id === id);
  useEffect(() => {
    if (id && !dialog.current?.open) dialog.current?.showModal();
    if (!id && dialog.current?.open) dialog.current.close();
  }, [id]);
  function display(key: string, value: unknown): string {
    if (key.endsWith("_cents") && typeof value === "number")
      return money(value);
    if (
      typeof value === "string" &&
      /^\d{4}-\d\d-\d\dT/.test(value) &&
      Number.isFinite(Date.parse(value))
    )
      return localTimestamp(value, timezone);
    if (Array.isArray(value))
      return value.map((item) => display(key, item)).join("\n\n");
    if (value && typeof value === "object")
      return Object.entries(value)
        .map(
          ([field, item]) =>
            `${field.replaceAll("_", " ")}: ${display(field, item)}`,
        )
        .join("\n");
    return safeWording(
      typeof value === "string" ? value : JSON.stringify(value),
      verdict,
    );
  }
  return (
    <dialog
      ref={dialog}
      className="evidence-dialog"
      onCancel={onClose}
      onClose={onClose}
      aria-labelledby="evidence-title"
    >
      <div className="row between">
        <h2 id="evidence-title">{e ? labels[e.kind] : "Source reference"}</h2>
        <button
          className="button small"
          onClick={onClose}
          aria-label="Close evidence"
        >
          <X size={18} />
        </button>
      </div>
      <p className="mono tiny muted break">{id}</p>
      {!e ? (
        <p className="empty">
          This source is an inbound event or an artifact not included in this
          task view. Its reference is preserved above.
        </p>
      ) : (
        <div className="stack">
          <div className="row wrap">
            <span className="badge">{e.source}</span>
            {e.is_fixture && (
              <span className="badge amber">Fixture evidence · simulated</span>
            )}
            <span className="badge">{claimLabel(e.claim_level, verdict)}</span>
          </div>
          <p className="tiny muted">
            Captured {localTimestamp(e.captured_at, timezone)}
          </p>
          {e.kind === "screenshot" && e.uri && (
            <div className="screenshot-preview">
              <img
                src={api.artifactUrl(e.id)}
                alt={`Evidence screenshot from ${e.source}`}
              />
            </div>
          )}
          <dl className="extracted">
            {Object.entries(e.extracted).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd className="break">{display(key, value)}</dd>
              </div>
            ))}
          </dl>
          {e.provider_ref && (
            <p className="tiny break">
              Session / provider reference:{" "}
              <span className="mono">{e.provider_ref}</span>
            </p>
          )}
          {e.uri && (
            <a
              className="button"
              href={api.artifactUrl(e.id)}
              target="_blank"
              rel="noreferrer"
            >
              Open source artifact
              <ExternalLink size={15} />
            </a>
          )}
          {e.sha256 && (
            <p className="tiny mono muted break">SHA-256 {e.sha256}</p>
          )}
        </div>
      )}
    </dialog>
  );
}
