export function OrbitMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`orbit-symbol ${className}`}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="20"
        cy="20"
        r="14"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeDasharray="1 5.1"
        strokeLinecap="round"
      />
      <circle cx="32" cy="12" r="4" fill="currentColor" />
      <circle cx="20" cy="20" r="4" fill="currentColor" opacity=".14" />
    </svg>
  );
}
