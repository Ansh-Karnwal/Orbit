"use client";
/* eslint-disable @next/next/no-img-element -- Evidence previews use the artifact endpoint directly. */
import { useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import { claimLabel, localTimestamp, money, safeWording } from "@/lib/format";
import {
  evidenceLabels,
  evidenceProvider,
  serviceName,
} from "@/lib/presentation";
import type { EvidenceArtifact, TaskView } from "@/lib/types";

export function EvidenceList({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  return (
    <section className="card">
      <div className="section-title">
        <div>
          <h2>Evidence library</h2>
          <p className="field-note">
            Messages and records behind your outcome.
          </p>
        </div>
        <span className="badge">{view.evidence.length} sources</span>
      </div>
      {!view.evidence.length && (
        <p className="empty">
          Messages and availability records will appear here as providers
          respond.
        </p>
      )}
      <div className="evidence-list">
        {view.evidence.toReversed().map((e) => (
          <button key={e.id} onClick={() => onEvidence(e.id)}>
            <FileText size={19} />
            <div>
              <strong>
                {evidenceProvider(view, e.id)} · {evidenceLabels[e.kind]}
              </strong>
              {typeof e.extracted.text === "string" && (
                <p className="evidence-excerpt">
                  {safeWording(
                    e.extracted.text.slice(0, 160),
                    view.verification?.verdict,
                  )}
                  {e.extracted.text.length > 160 ? "…" : ""}
                </p>
              )}
              <p>
                {claimLabel(e.claim_level, view.verification?.verdict)} ·{" "}
                {localTimestamp(e.captured_at, view.task.constraints.timezone)}
                {e.is_fixture ? " · Simulated" : ""}
              </p>
            </div>
            <ExternalLink size={15} />
          </button>
        ))}
      </div>
    </section>
  );
}

export function EvidenceDrawer({
  id,
  view,
  onClose,
}: {
  id: string | null;
  view: TaskView;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [resolved, setResolved] = useState<{
    id: string;
    evidence?: EvidenceArtifact;
    error?: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const direct = view.evidence.find((e) => e.id === id);
  const e = direct ?? (resolved?.id === id ? resolved.evidence : undefined);
  const error = resolved?.id === id ? resolved.error : undefined;
  const tz = view.task.constraints.timezone,
    verdict = view.verification?.verdict;
  useEffect(() => {
    if (id && !dialog.current?.open) dialog.current?.showModal();
    if (!id && dialog.current?.open) dialog.current.close();
  }, [id]);
  useEffect(() => {
    if (!id || direct) return;
    const abort = new AbortController();
    void api
      .source(view.task.id, id, abort.signal)
      .then((evidence) => {
        if (!abort.signal.aborted) setResolved({ id, evidence });
      })
      .catch(() => {
        if (!abort.signal.aborted)
          setResolved({
            id,
            error:
              "We couldn’t retrieve this source. Try again to load the original record.",
          });
      });
    return () => abort.abort();
  }, [id, direct, view.task.id, attempt]);
  function display(key: string, value: unknown): string {
    if (key.endsWith("_cents") && typeof value === "number")
      return money(value);
    if (key === "provider_id")
      return view.providers.find((p) => p.id === value)?.name ?? String(value);
    if (key === "service" && typeof value === "string")
      return serviceName(value);
    if (
      typeof value === "string" &&
      /^\d{4}-\d\d-\d\dT/.test(value) &&
      Number.isFinite(Date.parse(value))
    )
      return localTimestamp(value, tz);
    if (Array.isArray(value))
      return value.map((item) => display(key, item)).join("\n\n");
    if (value && typeof value === "object")
      return Object.entries(value)
        .map(([k, v]) => `${k.replaceAll("_", " ")}: ${display(k, v)}`)
        .join("\n");
    return safeWording(
      typeof value === "string" ? value : JSON.stringify(value),
      verdict,
    );
  }
  const labels: Record<string, string> = {
    provider_id: "Provider",
    service: "Service",
    slot_start: "Starts",
    slot_end: "Ends",
    visit_charge_cents: "Visit charge",
    confirmation_id: "Confirmation",
    cancellation_terms: "Cancellation",
    orbit_ref: "Booking reference",
    slots: "Available appointments",
    to: "Sent to",
  };
  const technical = new Set([
    "external_id",
    "idempotency_key",
    "channel",
    "screenshots",
    "source_id",
    "inbound_id",
  ]);
  const fields = e
    ? Object.entries(e.extracted).filter(
        ([key]) => key !== "text" && !technical.has(key),
      )
    : [];
  return (
    <dialog
      ref={dialog}
      className="evidence-dialog"
      onCancel={onClose}
      onClose={onClose}
      aria-labelledby="evidence-title"
    >
      <div className="row between">
        <h2 id="evidence-title">
          {e ? evidenceLabels[e.kind] : "Source message"}
        </h2>
        <button
          className="button small"
          onClick={onClose}
          aria-label="Close evidence"
        >
          <X size={18} />
        </button>
      </div>
      {!e ? (
        error ? (
          <div className="stack">
            <p className="error" role="alert">
              {error}
            </p>
            <button className="button" onClick={() => setAttempt((v) => v + 1)}>
              Try loading source again
            </button>
          </div>
        ) : (
          <p role="status">Loading the original source…</p>
        )
      ) : (
        <div className="stack">
          <p className="field-note">
            {view.providers.find((p) => p.id === e.extracted.provider_id)
              ?.name ?? evidenceProvider(view, e.id)}{" "}
            · {localTimestamp(e.captured_at, tz)}
            {e.is_fixture ? " · Simulated evidence" : ""}
          </p>
          <span className="badge">{claimLabel(e.claim_level, verdict)}</span>
          {typeof e.extracted.text === "string" && (
            <div className="source-text">
              {safeWording(e.extracted.text, verdict)}
            </div>
          )}
          {e.kind === "screenshot" && e.uri && (
            <div className="screenshot-preview">
              <img src={api.artifactUrl(e.id)} alt="Source screenshot" />
            </div>
          )}
          {fields.length > 0 && (
            <dl className="extracted">
              {fields.map(([key, value]) => (
                <div key={key}>
                  <dt>{labels[key] ?? serviceName(key)}</dt>
                  <dd>{display(key, value)}</dd>
                </div>
              ))}
            </dl>
          )}
          {e.uri && (
            <a
              className="button"
              href={api.artifactUrl(e.id)}
              target="_blank"
              rel="noreferrer"
            >
              Open source artifact <ExternalLink size={15} />
            </a>
          )}
          <details className="disclosure">
            <summary>Technical reference</summary>
            <div className="stack tiny mono break">
              <p>Source: {id}</p>
              <p>Artifact: {e.id}</p>
              <p>Adapter: {e.source}</p>
              {e.provider_ref && <p>Provider reference: {e.provider_ref}</p>}
              {e.sha256 && <p>SHA-256: {e.sha256}</p>}
              {Object.entries(e.extracted)
                .filter(([key]) => technical.has(key))
                .map(([key, value]) => (
                  <p key={key}>
                    {key}: {display(key, value)}
                  </p>
                ))}
            </div>
          </details>
        </div>
      )}
    </dialog>
  );
}
