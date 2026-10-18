"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Plus } from "lucide-react";
import { OrbitMark } from "./OrbitMark";
export function SiteHeader() {
  const pathname = usePathname();
  const workspace = pathname.startsWith("/tasks");
  return (
    <header className="site-header">
      <div className="header-inner">
        <Link href="/" className="brand" aria-label="Orbit home">
          <OrbitMark />
          orbit<span className="brand-period">.</span>
        </Link>
        <nav aria-label="Main navigation" className="header-links">
          <Link
            href="/tasks"
            aria-label="Your outcomes"
            aria-current={pathname === "/tasks" ? "page" : undefined}
          >
            Outcomes
          </Link>
          {workspace ? (
            <Link className="button primary small" href="/#intake">
              <Plus size={15} />
              New outcome
            </Link>
          ) : (
            <a href="#intake" className="button primary small">
              Try Orbit <ArrowUpRight size={15} />
            </a>
          )}
        </nav>
      </div>
    </header>
  );
}
