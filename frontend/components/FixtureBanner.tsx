import { FlaskConical } from "lucide-react";
import { hasFixtures } from "@/lib/format";
import type { TaskView } from "@/lib/types";
export function FixtureBanner({ view }: { view: TaskView }) {
  return hasFixtures(view) ? (
    <div className="notice fixture-banner" role="note">
      <FlaskConical size={15} />
      <strong>FIXTURE MODE</strong>
      <span className="fixture-tag">Simulated sandbox</span>
    </div>
  ) : null;
}
export function IntegrationChips({ view }: { view: TaskView }) {
  const names: Record<string, string> = {
    photon: "Photon",
    browser_use: "Browser Use",
    creao: "CREAO",
    llm: "Language Model",
  };
  return (
    <div className="row wrap integration-chips">
      {Object.entries(view.integrations).map(([name, status]) => (
        <span key={name} className="integration-chip">
          <span className={status === "live" ? "dot live" : "dot"} />
          <span className="chip-name">{names[name] ?? name}</span>
          <span className="chip-status">{status === "manual-handoff" ? "ready" : status}</span>
        </span>
      ))}
    </div>
  );
}
