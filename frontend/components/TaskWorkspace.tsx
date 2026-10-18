"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  FileCheck2,
  GitBranch,
  LayoutDashboard,
  RefreshCw,
  Settings2,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { useTaskStream } from "@/lib/useTaskStream";
import { isComplete, localRange, money, safeWording } from "@/lib/format";
import { serviceName, taskLabel } from "@/lib/presentation";
import { OrbitLoop } from "./OrbitLoop";
import { FixtureBanner, IntegrationChips } from "./FixtureBanner";
import { ApprovalCard } from "./ApprovalCard";
import { ProviderCard } from "./ProviderCard";
import { EvidenceDrawer, EvidenceList } from "./EvidenceDrawer";
import { CompletionSummary, VerificationPanel } from "./VerificationPanel";
import { Plan, Timeline } from "./PlanTimeline";
import DemoPanel from "./DemoPanel";
const tabs = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "providers", label: "Providers", icon: Users },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "evidence", label: "Evidence", icon: FileCheck2 },
  { id: "plan", label: "The plan", icon: GitBranch },
] as const;
type Tab = (typeof tabs)[number]["id"];
export default function TaskWorkspace({
  id,
  demoMode = false,
}: {
  id: string;
  demoMode?: boolean;
}) {
  const { view, error, errorStatus, connection, refresh } = useTaskStream(id);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [actionError, setActionError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  async function reload() {
    setRefreshing(true);
    try {
      await refresh();
    } catch {
      /* Stream displays the failure. */
    } finally {
      setRefreshing(false);
    }
  }
  async function stop() {
    setStopping(true);
    setActionError("");
    try {
      await api.cancel(id);
      await refresh();
    } catch {
      setActionError(
        "We couldn’t stop coordination. Refresh to check the current state and try again.",
      );
    } finally {
      setStopping(false);
    }
  }
  if (!view)
    return (
      <main id="main" className="loading-workspace">
        {!error && <div className="loading-orbit" />}
        <h1>
          {errorStatus === 404
            ? "Outcome not found"
            : error
              ? "We couldn’t load this outcome"
              : "Bringing your request together"}
        </h1>
        <p>
          {errorStatus === 404
            ? "This request may have been removed or the link may be out of date."
            : error
              ? "Check your connection and try again."
              : "Loading your request and its latest progress…"}
        </p>
        <div className="row wrap">
          <Link className="button" href="/tasks">
            Your outcomes
          </Link>
          {error && errorStatus !== 404 && (
            <button className="button primary" onClick={() => void reload()}>
              Retry
            </button>
          )}
          <Link className="text-link" href="/#intake">
            Create a new outcome
          </Link>
        </div>
      </main>
    );
  const tz = view.task.constraints.timezone,
    verdict = view.verification?.verdict;
  const finished = isComplete(view);
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(
    view.task.status,
  );
  const requested = terminal
    ? []
    : view.approvals.filter((a) => a.status === "requested");
  const history = view.approvals.filter((a) => a.status !== "requested");
  const invalidated = history.filter((a) => a.status === "invalidated").at(-1);
  const needsAttention =
    view.task.status === "BLOCKED" || view.task.status === "FAILED";
  const possibleBooking =
    view.approvals.some((a) => a.status === "approved") ||
    view.evidence.some((e) => e.kind === "portal_confirmation");
  const canRevise = needsAttention && !possibleBooking;
  const providers = (
    <section className="provider-section">
      <div className="section-title">
        <h2>Compare providers</h2>
        <span className="section-count">{view.providers.length} providers</span>
      </div>
      <div className="grid-two">
        {view.providers.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            view={view}
            onEvidence={setEvidenceId}
          />
        ))}
      </div>
    </section>
  );
  const decisions = history.length > 0 && (
    <details className="card disclosure">
      <summary>
        Previous decisions <span className="badge">{history.length}</span>
      </summary>
      <div className="stack">
        {history.map((a) => (
          <ApprovalCard
            key={a.id}
            approval={a}
            timezone={tz}
            verdict={verdict}
            onRefresh={refresh}
          />
        ))}
      </div>
    </details>
  );
  return (
    <main id="main" className="workspace-main">
      <div className="task-heading">
        <div>
          <h1>{serviceName(view.task.constraints.service)}</h1>
          <p className="outcome-line">
            {safeWording(
              view.task.outcome_text.split("\nAppointment window:")[0],
              verdict,
            )}
          </p>
        </div>
        <div className="task-heading-actions">
          <span
            className={`badge status ${finished ? "green" : needsAttention || requested.length > 0 ? "amber" : ""}`}
          >
            <span className="dot" />
            {taskLabel(view)}
          </span>
          <button
            className="refresh-button"
            aria-label="Refresh task"
            disabled={refreshing}
            onClick={() => void reload()}
          >
            <RefreshCw size={16} className={refreshing ? "spin" : ""} />
          </button>
        </div>
      </div>
      <div className="constraints-summary">
        <span>
          <strong>{money(view.task.constraints.max_visit_charge_cents)}</strong>{" "}
          maximum visit charge
        </span>
        <span>
          {localRange(
            view.task.constraints.window_start,
            view.task.constraints.window_end,
            tz,
          )}
        </span>
      </div>
      <FixtureBanner view={view} />
      {connection !== "connected" && (
        <p className="notice" role="status">
          Reconnecting to updates. Decisions will be available when the
          connection returns.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          We couldn’t retrieve the latest update. Refresh before taking action.
        </p>
      )}
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}
      {needsAttention && (
        <section className="card recovery-card">
          <h2>
            {canRevise
              ? "Choose your next step"
              : "Your booking needs attention"}
          </h2>
          <p>
            {safeWording(
              view.task.status_reason ||
                "The request needs your attention before coordination can continue.",
              verdict,
            )}
          </p>
          <div className="row wrap">
            {canRevise ? (
              <Link
                className="button primary"
                href={`/?revise=${encodeURIComponent(id)}#intake`}
              >
                Revise as a new request
              </Link>
            ) : (
              <button
                className="button primary"
                onClick={() => setActiveTab("evidence")}
              >
                Review booking evidence
              </button>
            )}
            {!terminal && (
              <button
                className="button"
                disabled={stopping || connection !== "connected"}
                onClick={() => void stop()}
              >
                {stopping ? "Stopping…" : "Stop coordination"}
              </button>
            )}
          </div>
          {possibleBooking && (
            <p className="field-note">
              A booking may already exist. Stopping coordination does not cancel
              a provider booking. Check the evidence before making another
              request.
            </p>
          )}
        </section>
      )}
      {view.task.status === "CANCELLED" && (
        <section className="notice">
          <strong>Coordination stopped.</strong>
          <p>
            Your request and its evidence remain available here. Existing
            provider bookings are not cancelled.
          </p>
        </section>
      )}
      {activeTab === "overview" && <CompletionSummary view={view} />}
      <div className="workspace-tabs" role="tablist" aria-label="Task views">
        {tabs.map(({ id: tab, label, icon: Icon }, i) => (
          <button
            key={tab}
            id={`tab-${tab}`}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls="workspace-panel"
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => setActiveTab(tab)}
            onKeyDown={(e) => {
              const next =
                e.key === "ArrowRight"
                  ? (i + 1) % tabs.length
                  : e.key === "ArrowLeft"
                    ? (i + tabs.length - 1) % tabs.length
                    : e.key === "Home"
                      ? 0
                      : e.key === "End"
                        ? tabs.length - 1
                        : null;
              if (next !== null) {
                e.preventDefault();
                setActiveTab(tabs[next].id);
                document.getElementById(`tab-${tabs[next].id}`)?.focus();
              }
            }}
          >
            <Icon size={16} />
            {label}
            {tab === "evidence" && (
              <span className="badge">{view.evidence.length}</span>
            )}
          </button>
        ))}
      </div>
      {activeTab !== "overview" && requested.length > 0 && (
        <div className="tab-action">
          <span>Your proposal is ready for review.</span>
          <button
            className="button small"
            onClick={() => setActiveTab("overview")}
          >
            Review proposal
          </button>
        </div>
      )}
      <div
        id="workspace-panel"
        className="workspace-panel"
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
      >
        {activeTab === "overview" && (
          <>
            {invalidated && !finished && (
              <section className="withdrawal">
                <h2>Previous approval withdrawn</h2>
                <p>
                  {safeWording(
                    invalidated.invalidated_reason ??
                      "The terms changed. Please review the replacement proposal.",
                    verdict,
                  )}
                </p>
              </section>
            )}
            {!finished && (
              <div className="overview-layout">
                <div className="stack decision-column">
                  {requested.length ? (
                    requested.map((a) => (
                      <ApprovalCard
                        key={a.id}
                        approval={a}
                        timezone={tz}
                        verdict={verdict}
                        onRefresh={refresh}
                        disabled={connection !== "connected" || !!error}
                        budget={view.task.constraints.max_visit_charge_cents}
                      />
                    ))
                  ) : !needsAttention && !terminal ? (
                    <section className="card stack">
                      <h2>
                        {possibleBooking
                          ? "Checking the result"
                          : "Finding your options"}
                      </h2>
                      <p className="muted">
                        {possibleBooking
                          ? "Orbit is checking the provider’s response against your approved terms."
                          : "We’re collecting provider quotes and checking available appointments. Your proposal will appear here."}
                      </p>
                    </section>
                  ) : (
                    <section className="card stack">
                      <h2>Request history</h2>
                      <p className="muted">
                        Review the provider responses and previous decisions for
                        this request.
                      </p>
                      <button
                        className="button"
                        onClick={() => setActiveTab("activity")}
                      >
                        View activity
                      </button>
                    </section>
                  )}
                  {view.verification && (
                    <VerificationPanel view={view} onEvidence={setEvidenceId} />
                  )}
                </div>
                {providers}
              </div>
            )}
            {finished && (
              <>
                <details className="card disclosure">
                  <summary>
                    What we verified{" "}
                    <span className="badge">
                      {view.verification?.predicates.length} checks
                    </span>
                  </summary>
                  <VerificationPanel view={view} onEvidence={setEvidenceId} />
                </details>
                <details className="card disclosure">
                  <summary>Providers compared</summary>
                  {providers}
                </details>
              </>
            )}
            {decisions}
          </>
        )}
        {activeTab === "providers" && providers}
        {activeTab === "activity" && (
          <Timeline view={view} onEvidence={setEvidenceId} />
        )}
        {activeTab === "evidence" && (
          <EvidenceList view={view} onEvidence={setEvidenceId} />
        )}
        {activeTab === "plan" && (
          <>
            <OrbitLoop view={view} />
            <Plan view={view} />
          </>
        )}
      </div>
      <DemoPanel
        view={view}
        enabled={view.task.mode === "fixture" || demoMode}
        onRefresh={refresh}
      />
      <details className="system-details disclosure">
        <summary>
          <Settings2 size={15} />
          Connection details
        </summary>
        <div className="system-content">
          <p className="field-note" role="status">
            {connection === "connected"
              ? "Updates connected"
              : "Reconnecting to updates…"}
          </p>
          <IntegrationChips view={view} />
        </div>
      </details>
      <EvidenceDrawer
        id={evidenceId}
        view={view}
        onClose={() => setEvidenceId(null)}
      />
    </main>
  );
}
