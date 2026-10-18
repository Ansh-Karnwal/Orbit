import { FlaskConical } from "lucide-react";
import { hasFixtures } from "@/lib/format";
import type { TaskView } from "@/lib/types";
export function FixtureBanner({ view }: { view: TaskView }) {
  return hasFixtures(view) ? (
    <div className="fixture-banner" role="note">
      <FlaskConical size={15} />
      <span>
        <strong>FIXTURE MODE</strong> ·{" "}
        {view.task.mode === "fixture"
          ? "Demo with simulated providers and evidence. No real service visit is booked."
          : "Some actions or evidence are simulated. Check each source for its origin."}
      </span>
    </div>
  ) : null;
}
export function IntegrationChips({ view }: { view: TaskView }) {
  const names: Record<string, string> = {
    photon: "Messaging",
    browser_use: "Browser",
    creao: "Workflow import",
    llm: "Language model",
  };
  return (
    <div className="integration-chips">
      {Object.entries(view.integrations).map(([name, status]) => (
        <span key={name} className="integration-chip">
          <span className="dot" />
          {names[name] ?? name}
          <span className="muted">
            {status === "fixture" ? "simulated" : status}
          </span>
        </span>
      ))}
    </div>
  );
}
