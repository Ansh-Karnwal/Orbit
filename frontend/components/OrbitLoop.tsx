import { isComplete } from "@/lib/format";
import type { TaskView } from "@/lib/types";

export function OrbitLoop({ view }: { view: TaskView }) {
  const requested = view.approvals.some((a) => a.status === "requested");
  const approved = view.approvals.some((a) => a.status === "approved");
  const finished = isComplete(view);
  const phase = finished
    ? 4
    : approved || view.verification
      ? 3
      : requested
        ? 2
        : 1;
  const stages = [
    ["Your request", "Boundaries set"],
    ["Providers", "Quotes and availability"],
    ["Your decision", "Exact terms for approval"],
    ["Verification", "Evidence checked"],
  ];
  return (
    <ol className="progress-track" aria-label="Coordination progress">
      {stages.map(([label, description], i) => (
        <li
          key={label}
          className={i < phase ? "done" : i === phase ? "current" : ""}
          aria-current={i === phase ? "step" : undefined}
        >
          {label}
          <small>{description}</small>
        </li>
      ))}
    </ol>
  );
}
