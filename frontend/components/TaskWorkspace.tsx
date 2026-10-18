"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  FileCheck2,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  RefreshCw,
  Users,
} from "lucide-react";
import { useTaskStream } from "@/lib/useTaskStream";
import { isComplete, safeWording } from "@/lib/format";
import { OrbitLoop } from "./OrbitLoop";
import { FixtureBanner, IntegrationChips } from "./FixtureBanner";
import { ApprovalCard } from "./ApprovalCard";
import { ProviderGallery } from "./ProviderGallery";
import { QuestionCard } from "./QuestionCard";
import { serviceLabel, statusLabel } from "@/lib/labels";
import { EvidenceDrawer, EvidenceList } from "./EvidenceDrawer";
import { CompletionSummary, VerificationPanel } from "./VerificationPanel";
import { Plan, Timeline } from "./PlanTimeline";
import DemoPanel from "./DemoPanel";
import type { TaskStatus } from "@/lib/types";
const statuses: Record<TaskStatus, string> = {
  DRAFT: "Draft",
  PLANNING: "Building a plan",
  RUNNING: "Coordinating",
  AWAITING_APPROVAL: "Needs your approval",
  WAITING_EXTERNAL: "Waiting on providers",
  BLOCKED: "Blocked — needs input",
  VERIFYING: "Verifying",
  COMPLETED: "Verification pending",
  FAILED: "Verification failed",
  CANCELLED: "Cancelled",
};
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
  const { view, error, connection, refresh } = useTaskStream(id),
    [evidenceId, setEvidenceId] = useState<string | null>(null),
    [refreshing, setRefreshing] = useState(false),
    [activeTab, setActiveTab] = useState<Tab>("overview");
  async function reload() {
    setRefreshing(true);
    try {
      await refresh();
    } catch {
      /* Stream reports errors. */
    } finally {
      setRefreshing(false);
    }
  }
  if (!view)
    return (
      <main id="main" className="loading-workspace">
        <div className="loading-orbit" />
        <p className="loading">
          {error ?? "Getting your moving parts together…"}
        </p>
        <Link href="/" className="text-link">
          ← Back to intake
        </Link>
        {error && (
          <button className="button" onClick={() => void reload()}>
            Retry
          </button>
        )}
      </main>
    );
  const tz = view.task.constraints.timezone,
    verdict = view.verification?.verdict,
    service = serviceLabel(view.task.constraints.service);
  const requested = view.approvals.filter((a) => a.status === "requested"),
    past = view.approvals.filter((a) => a.status !== "requested");
  const finished = isComplete(view);
  function selectTab(tab: Tab) {
    setActiveTab(tab);
  }
  const show = (tab: Tab) => activeTab === "overview" || activeTab === tab;
  return (
    <div className="workspace-shell">
      <main id="main" className="workspace-main">
        <div className="row between workspace-top">
          <Link href="/" className="back-link">
            <ArrowLeft size={15} />
            <span>Outcomes</span>
            <ChevronRight size={13} />
            <span className="current-crumb">{service}</span>
          </Link>
          <div className="row">
            <IntegrationChips view={view} />
          </div>
        </div>
        <div className="task-heading">
          <div>
            <h1>{service}</h1>
            <p className="outcome-line">
              {safeWording(view.task.outcome_text, verdict)}
            </p>
          </div>
          <div className="task-heading-actions">
            <span
              className={`badge status ${finished ? "green" : view.task.status === "FAILED" ? "red" : "amber"}`}
            >
              <span className="dot" />
              {finished
                ? "Verified & complete"
                : statusLabel(
                    view.task.status,
                    view.task.reason_code,
                    statuses[view.task.status],
                  )}
            </span>
            <button
              className="refresh-button"
              title="Refresh task"
              aria-label="Refresh task"
              disabled={refreshing}
              onClick={() => void reload()}
            >
              <RefreshCw size={15} className={refreshing ? "spin" : ""} />
            </button>
          </div>
        </div>
        <FixtureBanner view={view} />
        {connection !== "connected" && (
          <p className="notice" role="status">
            {connection === "reconnecting" ? "Reconnecting…" : "Connecting…"}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <CompletionSummary view={view} />
        <div className="workspace-tabs" role="tablist" aria-label="Task views">
          {tabs.map(({ id: tab, label, icon: Icon }, i) => (
            <button
              key={tab}
              id={`tab-${tab}`}
              role="tab"
              aria-selected={activeTab === tab}
              aria-controls="workspace-panel"
              tabIndex={activeTab === tab ? 0 : -1}
              onClick={() => selectTab(tab)}
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
              <Icon size={15} />
              {label}
              {tab === "evidence" && <span>{view.evidence.length}</span>}
            </button>
          ))}
          <span className="stream-indicator">
            <span className="live-dot" />
            {connection === "connected" ? "Updates connected" : "Reconnecting"}
          </span>
        </div>
        {view.task.status_reason && (
          <p className="status-reason">
            {safeWording(view.task.status_reason, verdict)}
          </p>
        )}
        <div className="workspace-grid">
          <div
            id="workspace-panel"
            role="tabpanel"
            aria-labelledby={`tab-${activeTab}`}
            key={activeTab}
            className="stack workspace-content"
          >
            {show("providers") && (
              <section className="provider-section">
                <div className="section-title">
                  <div>
                    <h2>Compare providers</h2>
                  </div>
                  <span className="section-count">
                    {view.providers.length} providers
                  </span>
                </div>
                <ProviderGallery view={view} onEvidence={setEvidenceId} />
              </section>
            )}
            {activeTab === "overview" &&
              past
                .filter((a) => a.status === "invalidated")
                .map((a) => (
                  <ApprovalCard
                    key={a.id}
                    approval={a}
                    timezone={tz}
                    verdict={verdict}
                    onRefresh={refresh}
                  />
                ))}
            {show("activity") && (
              <Timeline view={view} onEvidence={setEvidenceId} />
            )}
            {show("evidence") && (
              <EvidenceList
                evidence={view.evidence}
                timezone={tz}
                verdict={verdict}
                onEvidence={setEvidenceId}
              />
            )}
            {activeTab === "plan" && <Plan view={view} />}
          </div>
          <aside className="stack decision-column">
            <div className="decision-sticky">
              {view.open_question && (
                <QuestionCard
                  key={view.open_question.question_id}
                  view={view}
                  question={view.open_question}
                  onRefresh={refresh}
                />
              )}
              {requested.length ? (
                requested.map((a) => (
                  <ApprovalCard
                    key={a.id}
                    approval={a}
                    timezone={tz}
                    verdict={verdict}
                    onRefresh={refresh}
                    disabled={connection !== "connected" || !!error}
                  />
                ))
              ) : past.some(
                  (a) => a.status === "approved" || a.status === "rejected",
                ) ? (
                past
                  .filter(
                    (a) => a.status === "approved" || a.status === "rejected",
                  )
                  .slice(-1)
                  .map((a) => (
                    <ApprovalCard
                      key={a.id}
                      approval={a}
                      timezone={tz}
                      verdict={verdict}
                      onRefresh={refresh}
                    />
                  ))
              ) : view.open_question ? null : (
                <section className="card next-decision">
                  <span className="decision-halo">
                    <LockKeyhole size={24} />
                  </span>

                  <h2>Finding your options</h2>
                  <p>Your proposal will appear here for review.</p>
                  <span className="badge">
                    <span className="thinking-dots">
                      <i />
                      <i />
                      <i />
                    </span>
                    Coordination in progress
                  </span>
                </section>
              )}
              <VerificationPanel view={view} onEvidence={setEvidenceId} />
              {activeTab !== "plan" && (
                <button className="plan-link" onClick={() => selectTab("plan")}>
                  <span className="float-icon blue">
                    <GitBranch size={18} />
                  </span>
                  <span>
                    <strong>View the plan</strong>
                    <small>Steps and revisions</small>
                  </span>
                  <ArrowUpRight size={17} />
                </button>
              )}
            </div>
          </aside>
        </div>
        <DemoPanel
          view={view}
          enabled={view.task.mode === "fixture" || demoMode}
          onRefresh={refresh}
        />
        <EvidenceDrawer
          id={evidenceId}
          evidence={view.evidence}
          timezone={tz}
          verdict={verdict}
          onClose={() => setEvidenceId(null)}
        />
        <OrbitLoop view={view} onSelectTab={selectTab} />
      </main>
    </div>
  );
}
