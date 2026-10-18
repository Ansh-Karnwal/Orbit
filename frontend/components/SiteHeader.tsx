"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Plus, ShieldCheck } from "lucide-react";
import { OrbitMark } from "./OrbitMark";
export function SiteHeader() {
  const workspace = usePathname().startsWith("/tasks/");
  return (
    <header className={`site-header ${workspace ? "workspace-header" : ""}`}>
      <div className="header-inner">
        <Link href="/" className="brand" aria-label="Orbit home">
          <OrbitMark />
          orbit<span className="brand-period">.</span>
        </Link>
        {workspace ? (
          <>
            <span className="workspace-header-label">
              Your coordination workspace
            </span>
            <Link className="button small" href="/#intake">
              <Plus size={15} />
              New outcome
            </Link>
          </>
        ) : (
          <>
            <nav aria-label="Main navigation" className="landing-nav">
              <a href="#intake">The demo</a>
            </nav>
            <a href="#intake" className="button primary small">
              Try Orbit
              <ArrowUpRight size={15} />
            </a>
          </>
        )}
      </div>
      {workspace && (
        <span className="header-trust">
          <ShieldCheck size={13} />
          You stay in control
        </span>
      )}
    </header>
  );
}
