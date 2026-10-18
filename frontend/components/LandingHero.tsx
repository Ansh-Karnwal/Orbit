import { ArrowRight, ArrowUpRight, Check, LockKeyhole } from "lucide-react";
import { OrbitMark } from "./OrbitMark";
import styles from "./LandingHero.module.css";

export function LandingHero() {
  return (
    <>
      <section className={styles.hero} aria-labelledby="hero-title">
        <div className={styles.copy}>
          <span className="eyebrow">Orbit · Everyday coordination</span>
          <h1 id="hero-title">
            Life’s calling.
            <br />
            <em>Skip the hold.</em>
          </h1>
          <p>
            Repairs and appointments, coordinated end to end.
            <br />
            You make the final call.
          </p>
          <a href="#intake" className="button primary large">
            Try the repair demo <ArrowUpRight size={18} />
          </a>
          <small>Compare providers. Approve the terms. Check the result.</small>
        </div>
        <svg
          className={styles.ribbon}
          viewBox="0 0 1440 280"
          fill="none"
          aria-hidden="true"
        >
          <defs>
            <path
              id="orbit-request-thread"
              d="M-180 116 C80 142 276 156 292 68 C312 -50 103 -30 153 91 C217 246 455 273 724 222 C940 180 1204 95 1550 94"
            />
            <path
              id="orbit-handled-thread"
              d="M760 224 C1010 206 1140 100 1540 100"
            />
          </defs>
          <text className={styles.looseText}>
            <textPath href="#orbit-request-thread">
              Find a provider. Find a time. Compare the quote. Check the travel
              fee. Ask about cancellation. A little less chasing, a little more
              living.
            </textPath>
          </text>
          <use href="#orbit-handled-thread" className={styles.ribbonLine} />
          <text className={styles.ribbonText} dy="6">
            <textPath href="#orbit-handled-thread" startOffset="5%">
              Your time. Your budget. Your final say. We’ll bring it all
              together.
            </textPath>
          </text>
        </svg>
        <span className={styles.ribbonMark} aria-hidden="true">
          <OrbitMark />
        </span>
      </section>
      <section className={styles.showcase} id="how" aria-labelledby="how-title">
        <div className={styles.sectionHeading}>
          <span className="eyebrow">From request to result</span>
          <h2 id="how-title">
            Less chasing.
            <br />
            <em>More living.</em>
          </h2>
          <p>
            The messages, the quotes, the unexpected fees.
            <br />
            One place to bring the moving parts together.
          </p>
        </div>
        <div
          className={styles.demo}
          aria-label="Illustrative coordination example"
        >
          <div className={styles.requestCard}>
            <div className={styles.cardLabel}>
              <span>Your request</span>
              <span>Example</span>
            </div>
            <p>
              “My dishwasher needs a visit. Tuesday afternoon works. Keep it
              under $150, and ask me before booking.”
            </p>
            <div className={styles.boundaries}>
              <span>Tuesday, 2–5 p.m.</span>
              <span>$150 visit budget</span>
            </div>
          </div>
          <span className={styles.arrow} aria-hidden="true">
            <ArrowRight size={24} />
          </span>
          <div className={styles.previewCard}>
            <div className={styles.cardLabel}>
              <span>A decision for you</span>
              <span className={styles.exampleTag}>Example</span>
            </div>
            <div className={styles.provider}>
              <div>
                <h3>Bayside Appliance Service</h3>
                <p>Tuesday · 2:30–3:30 p.m.</p>
              </div>
              <span className={styles.price}>$145</span>
            </div>
            <div className={styles.check}>
              <Check size={16} /> Diagnostic visit, including travel
            </div>
            <div className={styles.check}>
              <Check size={16} /> $5 below your visit budget
            </div>
            <div className={styles.approvalNote}>
              <LockKeyhole size={16} /> You approve the exact terms before
              booking.
            </div>
          </div>
        </div>
        <div className={styles.how} aria-label="How Orbit works">
          <div>
            <span>01</span>
            <strong>Set your boundaries</strong>
            <p>A time window, a visit budget, and what matters to you.</p>
          </div>
          <div>
            <span>02</span>
            <strong>Review your options</strong>
            <p>Compare providers and inspect the messages behind each quote.</p>
          </div>
          <div>
            <span>03</span>
            <strong>Approve, then verify</strong>
            <p>Orbit checks the result against the terms you approved.</p>
          </div>
        </div>
      </section>
    </>
  );
}
