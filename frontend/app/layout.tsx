import type { Metadata } from "next";
import { SiteHeader } from "@/components/SiteHeader";
import "./globals.css";
export const metadata: Metadata = {
  title: "Orbit · Outcome coordination",
  description: "Coordinated with context. Completed with evidence.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // Extensions (e.g. Grammarly) add attributes to <html>/<body> before hydration; this only silences those two elements.
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <SiteHeader />
        {children}
        <footer>
          <span className="footer-brand">orbit.</span>
          <span>Less chasing. More living.</span>
          <span className="footer-note">Built around your boundaries.</span>
        </footer>
      </body>
    </html>
  );
}
