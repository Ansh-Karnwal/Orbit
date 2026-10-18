"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Plus, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import type { UserInfo } from "@/lib/types";
import { OrbitMark } from "./OrbitMark";

function UserChip() {
  const [user, setUser] = useState<UserInfo | null>(null);
  useEffect(() => {
    const load = () => void api.me().then(setUser).catch(() => setUser(null));
    load();
    window.addEventListener("orbit:auth", load);
    return () => window.removeEventListener("orbit:auth", load);
  }, []);
  if (!user) return null;
  return (
    <Link className="user-chip" href="/signin" title="Account">
      <UserRound size={14} />
      {user.authenticated ? user.display_name : "Sign in"}
    </Link>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const workspace = pathname.startsWith("/tasks");
  return (
    <>
      {pathname === "/" && (
        <div className="brand-note">
          Your plans. Your boundaries. Your final say.
        </div>
      )}
      <header className="site-header">
        <div className="header-inner">
          <Link href="/" className="brand" aria-label="Orbit home">
            <OrbitMark />
            orbit<span className="brand-period">.</span>
          </Link>
          <nav aria-label="Main navigation" className="header-links">
            {pathname === "/" && (
              <a className="how-link" href="#how">
                How it works
              </a>
            )}
            <Link
              href="/tasks"
              aria-label="Your outcomes"
              aria-current={pathname === "/tasks" ? "page" : undefined}
            >
              Outcomes
            </Link>
            <Link
              href="/services"
              aria-current={pathname === "/services" ? "page" : undefined}
            >
              Services
            </Link>
            <UserChip />
            {workspace ? (
              <Link className="button primary small" href="/#intake">
                <Plus size={15} />
                New outcome
              </Link>
            ) : pathname === "/" ? (
              <a href="#intake" className="button primary small">
                Try Orbit <ArrowUpRight size={15} />
              </a>
            ) : (
              <Link href="/#intake" className="button primary small">
                Try Orbit <ArrowUpRight size={15} />
              </Link>
            )}
          </nav>
        </div>
      </header>
    </>
  );
}
