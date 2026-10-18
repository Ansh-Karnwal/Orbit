import { ArrowUpRight, Check, LockKeyhole, Wrench } from "lucide-react";
import styles from "./LandingHero.module.css";

export function LandingHero() {
  return (
    <>
      <section className={styles.hero} aria-labelledby="hero-title">
        <div className={styles.copy}>
          <span className="eyebrow">A little less on your list</span>
          <h1 id="hero-title">
            Life’s calling.
            <br />
            <em>Skip the hold.</em>
          </h1>
          <p>
            Tell us what needs doing. Orbit compares providers, brings you the
            terms, and checks the booking after you approve.
          </p>
          <div className={styles.ctaRow}>
            <a href="#intake" className="button primary large">
              Try the repair demo <ArrowUpRight size={17} />
            </a>
            <small>You make the final call.</small>
          </div>
        </div>
        <div
          className={styles.preview}
          aria-label="Illustrative booking example"
        >
          <div className={styles.previewLabel}>
            <span>A request, brought together</span>
            <span>Example</span>
          </div>
          <div className={styles.previewCard}>
            <span className={styles.request}>
              <Wrench size={16} /> Dishwasher repair
            </span>
            <h2>Your Tuesday, sorted.</h2>
            <p>A diagnostic visit, within your $150 budget.</p>
            <div className={styles.provider}>
              <div>
                <strong>Bayside Appliance Service</strong>
                <small>Tuesday · 2:30–3:30 p.m.</small>
                <small>Diagnostic visit, including travel</small>
              </div>
              <span className={styles.price}>$145</span>
            </div>
            <div className="row">
              <LockKeyhole size={16} />
              <span>Ready for your approval</span>
            </div>
            <div className={styles.check}>
              <Check size={16} /> Exact terms checked before booking
            </div>
          </div>
        </div>
      </section>
      <div className={styles.how} aria-label="How Orbit works">
        <div>
          <strong>01 · Set your boundaries</strong>
          <p>Choose a time window and maximum visit charge.</p>
        </div>
        <div>
          <strong>02 · Review your options</strong>
          <p>Compare costs and terms, with messages you can inspect.</p>
        </div>
        <div>
          <strong>03 · Approve, then verify</strong>
          <p>Orbit checks the result against the terms you approved.</p>
        </div>
      </div>
    </>
  );
}
