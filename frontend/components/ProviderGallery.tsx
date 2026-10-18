"use client";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import type { ProviderSpec, TaskView } from "@/lib/types";
import { ProviderCard } from "./ProviderCard";

const AUTO_ADVANCE_MS = 6000;

type Group = "proposed" | "eligible" | "waiting" | "out";

function charge(view: TaskView, id: string): number {
  const f = view.facts.find(
    (x) =>
      x.key === `${id}.visit_charge_cents` &&
      (x.status === "confirmed" || x.status === "proposed"),
  );
  return typeof f?.value === "number" ? f.value : Number.MAX_SAFE_INTEGER;
}

/** Left to right: current proposal, other eligible (cheapest first), still waiting, then out. */
export function orderProviders(view: TaskView): ProviderSpec[] {
  const proposed = view.current_proposal?.provider_id;
  const group = (p: ProviderSpec): Group => {
    if (p.id === proposed) return "proposed";
    const reasons = view.eligibility[p.id];
    const replied = view.facts.some((f) => f.key.startsWith(`${p.id}.`));
    if (!replied) return "waiting";
    return reasons && reasons.length === 0 ? "eligible" : "out";
  };
  const rank: Record<Group, number> = { proposed: 0, eligible: 1, waiting: 2, out: 3 };
  return view.providers
    .map((p, i) => ({ p, i }))
    .sort(
      (a, b) =>
        rank[group(a.p)] - rank[group(b.p)] ||
        charge(view, a.p.id) - charge(view, b.p.id) ||
        a.i - b.i,
    )
    .map(({ p }) => p);
}

const REDUCED = "(prefers-reduced-motion: reduce)";
function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED).matches
  );
}
function subscribeReducedMotion(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function")
    return () => undefined;
  const mq = window.matchMedia(REDUCED);
  mq.addEventListener?.("change", onChange);
  return () => mq.removeEventListener?.("change", onChange);
}

export function ProviderGallery({
  view,
  onEvidence,
}: {
  view: TaskView;
  onEvidence: (id: string) => void;
}) {
  const ordered = useMemo(() => orderProviders(view), [view]);
  const accentIndex = useMemo(
    () => new Map(view.providers.map((p, i) => [p.id, i])),
    [view.providers],
  );
  const track = useRef<HTMLDivElement>(null);
  const reduced = useSyncExternalStore(
    subscribeReducedMotion,
    prefersReducedMotion,
    () => false,
  );
  const [active, setActive] = useState(0),
    [paused, setPaused] = useState(false),
    [hovered, setHovered] = useState(false);
  // Slide automatically only when there is somewhere to slide, motion is welcome, and the
  // person hasn't taken over.
  const playing = ordered.length > 2 && !reduced && !paused;
  const setPlaying = (next: boolean | ((p: boolean) => boolean)) =>
    setPaused(!(typeof next === "function" ? next(playing) : next));

  const scrollToIndex = useCallback(
    (i: number, smooth = true) => {
      const el = track.current;
      const slide = el?.children[i] as HTMLElement | undefined;
      if (!el || !slide) return;
      el.scrollTo?.({
        left: slide.offsetLeft, // the track is the slides' offsetParent (position: relative)
        behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto",
      });
      setActive(i);
    },
    [],
  );

  // A new proposal (e.g. after a price-change replan) slides back to the start.
  const proposed = view.current_proposal?.provider_id;
  useEffect(() => {
    scrollToIndex(0);
  }, [proposed, scrollToIndex]);

  useEffect(() => {
    if (!playing || hovered || ordered.length < 2) return;
    const t = setInterval(
      () => scrollToIndex((active + 1) % ordered.length),
      AUTO_ADVANCE_MS,
    );
    return () => clearInterval(t);
  }, [playing, hovered, active, ordered.length, scrollToIndex]);

  function onScroll() {
    const el = track.current;
    if (!el || !el.children.length) return;
    const width = (el.children[0] as HTMLElement).offsetWidth || 1;
    setActive(
      Math.min(ordered.length - 1, Math.round(el.scrollLeft / width)),
    );
  }

  const go = (delta: number) => {
    setPlaying(false); // any manual move hands control to the person
    scrollToIndex((active + delta + ordered.length) % ordered.length);
  };

  return (
    <section
      className="provider-gallery"
      aria-roledescription="carousel"
      aria-label="Providers in this sandbox"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setHovered(true)}
      onBlurCapture={() => setHovered(false)}
    >
      <div className="gallery-controls row">
        <span className="gallery-position" aria-live="polite">
          {ordered.length ? `${active + 1} of ${ordered.length}` : ""}
        </span>
        <button
          className="icon-button"
          aria-label="Previous provider"
          onClick={() => go(-1)}
          disabled={ordered.length < 2}
        >
          <ChevronLeft size={16} />
        </button>
        <button
          className="icon-button"
          aria-label="Next provider"
          onClick={() => go(1)}
          disabled={ordered.length < 2}
        >
          <ChevronRight size={16} />
        </button>
        {ordered.length > 2 && (
          <button
            className="icon-button"
            aria-label={playing ? "Pause sliding" : "Slide automatically"}
            aria-pressed={playing}
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </button>
        )}
      </div>
      <div
        ref={track}
        className="gallery-track"
        tabIndex={0}
        aria-label="Provider slides; use the arrow keys to move"
        onScroll={onScroll}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") {
            e.preventDefault();
            go(1);
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            go(-1);
          }
        }}
      >
        {ordered.map((provider, i) => (
          <div
            key={provider.id}
            className="gallery-slide"
            role="group"
            aria-roledescription="slide"
            aria-label={`${i + 1} of ${ordered.length}: ${provider.name}`}
          >
            <ProviderCard
              provider={provider}
              view={view}
              onEvidence={onEvidence}
              accent={accentIndex.get(provider.id) ?? i}
              proposed={provider.id === proposed}
            />
          </div>
        ))}
      </div>
      {ordered.length > 1 && (
        <div className="gallery-dots" role="tablist" aria-label="Choose a provider">
          {ordered.map((p, i) => (
            <button
              key={p.id}
              role="tab"
              aria-selected={i === active}
              aria-label={`Show ${p.name}`}
              className={i === active ? "active" : ""}
              onClick={() => {
                setPlaying(false);
                scrollToIndex(i);
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}
