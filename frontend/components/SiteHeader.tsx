"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, LayoutGrid, Plus, ShieldCheck, UserRound } from "lucide-react";
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
  const path = usePathname();
  const workspace = path.startsWith("/tasks/");
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
            <div className="row header-actions">
              <Link className="text-link" href="/services">
                <LayoutGrid size={14} />
                Services
              </Link>
              <UserChip />
              <Link className="button small" href="/#intake">
                <Plus size={15} />
                New outcome
              </Link>
            </div>
          </>
        ) : (
          <>
            <nav aria-label="Main navigation" className="landing-nav">
              <Link href="/#intake">The demo</Link>
              <Link href="/services">Services</Link>
            </nav>
            <div className="row header-actions">
              <UserChip />
              <Link href="/#intake" className="button primary small">
                Try Orbit
                <ArrowUpRight size={15} />
              </Link>
            </div>
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
