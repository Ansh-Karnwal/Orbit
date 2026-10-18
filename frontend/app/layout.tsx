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
    <html lang="en">
      <body>
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
