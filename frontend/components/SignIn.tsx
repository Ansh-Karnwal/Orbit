"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LogIn, LogOut, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { UserInfo } from "@/lib/types";

/** Demo sign-in (roadmap E): a name, no password. A real identity provider replaces only this. */
export default function SignIn() {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null),
    [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");

  useEffect(() => {
    void api
      .me()
      .then(setUser)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not reach Orbit"));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await api.login(name);
      setUser(u);
      window.dispatchEvent(new Event("orbit:auth"));
      router.push("/services");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    try {
      setUser(await api.logout());
      window.dispatchEvent(new Event("orbit:auth"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="signin-main">
      <section className="card signin-card" aria-labelledby="signin-title">
        <h1 id="signin-title">Sign in to Orbit</h1>
        <p className="notice">
          <ShieldAlert size={16} />
          Demo sign-in: just a name, no password. Your searches are kept separate from
          other names. A real identity provider replaces this before any public use.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {user?.authenticated ? (
          <div className="stack">
            <p>
              Signed in as <strong>{user.display_name}</strong>{" "}
              <span className="muted mono">({user.user_id})</span>
            </p>
            <button className="button" disabled={busy} onClick={() => void signOut()}>
              <LogOut size={15} />
              Sign out
            </button>
          </div>
        ) : (
          <form className="stack" onSubmit={submit}>
            <label className="field">
              Your name
              <input
                value={name}
                autoComplete="name"
                maxLength={60}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <button className="button primary" disabled={busy || !name.trim()}>
              <LogIn size={15} />
              {busy ? "Signing in…" : "Sign in"}
            </button>
            {user && !user.authenticated && user.auth_mode === "demo" && (
              <p className="muted">
                Not signed in: you&apos;re using the shared demo account.
              </p>
            )}
          </form>
        )}
      </section>
    </main>
  );
}
