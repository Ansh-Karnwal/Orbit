"use client";
import { useEffect, useId, useRef, useState } from "react";
import {
  CalendarDays,
  ChevronUp,
  LockKeyhole,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { isComplete, localRange, money } from "@/lib/format";
import type { TaskView } from "@/lib/types";

export function OrbitLoop({
  view,
  onSelectTab,
}: {
  view: TaskView;
  onSelectTab?: (tab: "overview" | "providers" | "evidence" | "activity" | "plan") => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const closeTimerRef = useRef<NodeJS.Timeout | null>(null);
  const gradientId = useId();
  const filterId = useId();

  const c = view.task.constraints;
  const tz = c.timezone;
  const requested = view.approvals.filter((a) => a.status === "requested");
  const finished = isComplete(view);
  const verdict = view.verification?.verdict;

  // Phase computation
  const phase = finished
    ? 4
    : view.verification !== null || view.task.status === "VERIFYING"
      ? 3
      : requested.length
        ? 2
        : view.facts.length
          ? 1
          : 0;

  // Active satellite status
  const providerCount = view.providers.length;
  const eligibleCount = Object.values(view.eligibility).filter(
    (reasons) => reasons && reasons.length === 0,
  ).length;

  const handleMouseEnter = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsOpen(true);
  };

  const handleMouseLeave = () => {
    closeTimerRef.current = setTimeout(() => {
      setIsOpen(false);
    }, 280);
  };

  const toggleOpen = () => {
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    setIsOpen((prev) => !prev);
  };

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  const handleStationClick = (tab: "overview" | "providers" | "evidence" | "activity" | "plan") => {
    onSelectTab?.(tab);
  };

  return (
    <aside
      className="orbit-dock"
      aria-label="Orbital coordination loop"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Floating Popover Card */}
      <div
        id="orbit-popover-card"
        className={`orbit-popover ${isOpen ? "open" : ""}`}
        role="region"
        aria-label="Orbit loop details"
      >
        <div className="orbit-popover-header">
          <div className="orbit-popover-title">
            <span className="live-dot" />
            <span>ORBIT OVERVIEW</span>
            <span className="orbit-popover-sub">
              {finished
                ? "· Completed"
                : requested.length
                  ? "· Action Needed"
                  : `· Phase 0${phase + 1}`}
            </span>
          </div>
          <button
            type="button"
            className="orbit-popover-close"
            onClick={() => setIsOpen(false)}
            aria-label="Close orbit loop overview"
          >
            <X size={15} />
          </button>
        </div>

        <div className="orbit-popover-body">
          {/* Background glow and ambient radial field */}
          <div className="orbit-ambient-glow" />

          {/* Center SVG Ring with traveling orbital particle */}
          <div className="orbit-canvas-wrapper">
            <svg
              className="orbit-canvas"
              viewBox="0 0 800 520"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.8" />
                  <stop offset="50%" stopColor="#818cf8" stopOpacity="0.6" />
                  <stop offset="100%" stopColor="#34d399" stopOpacity="0.9" />
                </linearGradient>
                <filter id={filterId} x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="6" result="blur" />
                  <feComposite in="SourceGraphic" in2="blur" operator="over" />
                </filter>
              </defs>

              {/* Outer concentric guide track */}
              <ellipse
                cx="400"
                cy="260"
                rx="370"
                ry="210"
                stroke="rgba(148, 163, 184, 0.12)"
                strokeWidth="1.5"
                strokeDasharray="6 8"
              />

              {/* Inner concentric guide track */}
              <ellipse
                cx="400"
                cy="260"
                rx="270"
                ry="150"
                stroke="rgba(148, 163, 184, 0.08)"
                strokeWidth="1"
                strokeDasharray="3 6"
              />

              {/* Main Elliptical Orbit Track */}
              <ellipse
                id="main-orbit-path"
                cx="400"
                cy="260"
                rx="330"
                ry="185"
                stroke={`url(#${gradientId})`}
                strokeWidth="2.5"
                strokeDasharray="12 6"
                className="orbit-track-path"
              />

              {/* Luminous Core Glow Aura */}
              <circle
                cx="400"
                cy="260"
                r="80"
                fill="rgba(56, 189, 248, 0.04)"
                filter={`url(#${filterId})`}
              />
              <circle
                cx="400"
                cy="260"
                r="60"
                stroke="rgba(56, 189, 248, 0.2)"
                strokeWidth="1.5"
                strokeDasharray="4 4"
                className="orbit-pulse-core"
              />

              {/* Traveling Satellite / Orbital Beacon */}
              <g className="orbit-traveling-satellite">
                <circle r="7" fill="#38bdf8" filter={`url(#${filterId})`} />
                <circle r="3.5" fill="#ffffff" />
              </g>
            </svg>

            {/* ORBIT CORE: Centered Hub inside the loop */}
            <div className="orbit-center-nucleus">
              <div className="nucleus-inner">
                <span className="nucleus-badge">
                  <span className="live-dot" />
                  ORBIT CORE
                </span>
                <h2 className="nucleus-title">
                  {finished
                    ? "Verified"
                    : requested.length
                      ? "Action Required"
                      : "Coordinating"}
                </h2>
              </div>
            </div>

            {/* 4 ORBITAL SATELLITE STATIONS ALONG THE LOOP */}

            {/* Station 1: North (12 o'clock) - MISSION BOUNDS */}
            <div
              className={`orbit-station station-north ${phase >= 0 ? "active" : ""}`}
              onClick={() => handleStationClick("overview")}
              role="button"
              tabIndex={0}
              title="Mission Bounds"
            >
              <div className="station-node-icon">
                <CalendarDays size={18} />
              </div>
              <div className="station-content">
                <span className="station-label">01 · BOUNDS</span>
                <span className="station-val">
                  {money(c.max_visit_charge_cents)}
                </span>
                <span className="station-sub">
                  {localRange(c.window_start, c.window_end, tz)}
                </span>
              </div>
            </div>

            {/* Station 2: East (3 o'clock) - SATELLITE PROVIDERS */}
            <div
              className={`orbit-station station-east ${phase >= 1 ? "active" : ""}`}
              onClick={() => handleStationClick("providers")}
              role="button"
              tabIndex={0}
              title="Candidate Providers"
            >
              <div className="station-node-icon purple">
                <Users size={18} />
              </div>
              <div className="station-content">
                <span className="station-label">02 · PROVIDERS</span>
                <span className="station-val">
                  {providerCount} Candidate{providerCount !== 1 ? "s" : ""}
                </span>
                <span className="station-sub">
                  {eligibleCount > 0 ? `${eligibleCount} Eligible` : "Awaiting response"}
                </span>
              </div>
            </div>

            {/* Station 3: South (6 o'clock) - DECISION GATEWAY */}
            <div
              className={`orbit-station station-south ${phase >= 2 ? "active" : ""} ${requested.length ? "pulse-amber" : ""}`}
              onClick={() => handleStationClick("overview")}
              role="button"
              tabIndex={0}
              title="Approval Gateway"
            >
              <div className="station-node-icon amber">
                <LockKeyhole size={18} />
              </div>
              <div className="station-content">
                <span className="station-label">03 · DECISION GATE</span>
                <span className="station-val">
                  {requested.length
                    ? "Approval Needed"
                    : phase > 2
                      ? "Approved"
                      : "Gate Ready"}
                </span>
              </div>
            </div>

            {/* Station 4: West (9 o'clock) - VERIFIER SENTINEL */}
            <div
              className={`orbit-station station-west ${phase >= 3 ? "active" : ""} ${finished ? "pulse-green" : ""}`}
              onClick={() => handleStationClick("evidence")}
              role="button"
              tabIndex={0}
              title="Verification Sentinel"
            >
              <div className="station-node-icon green">
                <ShieldCheck size={18} />
              </div>
              <div className="station-content">
                <span className="station-label">04 · VERIFICATION</span>
                <span className="station-val">
                  {finished
                    ? "PASS"
                    : verdict === "FAIL"
                      ? "FAIL"
                      : "Pending"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Dock Trigger Button in Bottom Left */}
      <button
        type="button"
        className={`orbit-dock-trigger ${isOpen ? "active" : ""}`}
        onClick={toggleOpen}
        aria-expanded={isOpen}
        aria-controls="orbit-popover-card"
        aria-label="Toggle Orbit Loop overview"
      >
        <span className="orbit-trigger-beacon">
          <span className="orbit-trigger-ring" />
          <span className="orbit-trigger-dot" />
        </span>
        <span className="orbit-trigger-title">Orbit Loop</span>
        <span className="orbit-trigger-status">
          {finished ? "Verified" : requested.length ? "Action" : `Phase 0${phase + 1}`}
        </span>
        <ChevronUp size={14} className={`orbit-trigger-chevron ${isOpen ? "rotated" : ""}`} />
      </button>
    </aside>
  );
}
