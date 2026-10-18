"use client";
import { useState } from "react";
import { ArrowUpRight, Pause, Play } from "lucide-react";
import styles from "./LandingHero.module.css";

export function LandingHero() {
  const [paused, setPaused] = useState(false);
  return (
    <section
      className={`${styles.hero} ${paused ? styles.paused : ""}`}
      aria-labelledby="hero-title"
    >
      <div className={styles.copy}>
        <h1 id="hero-title">
          Life’s calling.
          <br />
          <em>Skip the hold.</em>
        </h1>
        <p>
          Repairs and appointments, coordinated end-to-end.
          <br />
          You make the final call.
        </p>
        <div className={styles.ctaRow}>
          <a href="#intake" className={`button ${styles.cta}`}>
            Try Orbit <ArrowUpRight size={20} />
          </a>
        </div>
      </div>
      <svg
        className={styles.drawing}
        viewBox="0 0 1440 760"
        fill="none"
        aria-hidden="true"
        preserveAspectRatio="xMidYMid slice"
      >
        <path
          className={styles.thread}
          d="M-80 230 C210 190 80 680 286 625 C500 567 80 393 126 575 C175 766 537 730 735 653 S1140 550 1520 660"
        />
        <path
          className={styles.tail}
          d="M1030 695 C1150 660 1270 600 1340 465 C1410 330 1270 230 1190 323 C1100 430 1300 516 1520 360"
        />
        <g className={styles.orbit} data-testid="illustration-orbit">
          <circle
            cx="1235"
            cy="349"
            r="45"
            fill="#dfb9ed"
            stroke="#25291f"
            strokeWidth="2"
          />
          <path
            d="M1213 349h44m-22-22v44m-16-38 32 32m0-32-32 32"
            stroke="#25291f"
            strokeWidth="2"
          />
        </g>
        <g className={styles.note}>
          <rect
            x="200"
            y="520"
            width="166"
            height="66"
            rx="3"
            fill="#e9ed9e"
            stroke="#25291f"
            strokeWidth="1.5"
            transform="rotate(-12 283 553)"
          />
          <text
            x="283"
            y="559"
            textAnchor="middle"
            fill="#25291f"
            fontSize="19"
            fontFamily="Georgia, serif"
            fontStyle="italic"
            transform="rotate(-12 283 553)"
          >
            Tuesday, sorted?
          </text>
        </g>
      </svg>
      <button
        className={styles.pause}
        onClick={() => setPaused(!paused)}
        aria-label={
          paused
            ? "Play illustration animation"
            : "Pause illustration animation"
        }
      >
        {paused ? <Play size={14} /> : <Pause size={14} />}
      </button>
      <span className={styles.scroll}>
        A little less on your list. <span>↓</span>
      </span>
    </section>
  );
}
