import Link from "next/link";
import ThemeToggle from "./theme-toggle";
import WaitlistTrigger from "./waitlist-trigger";

export default function SiteHeader({ isHome = false }) {
  const sectionPrefix = isHome ? "" : "/";

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link href="/" className="wordmark">
          Solus
        </Link>
        <nav className="site-nav" aria-label="Primary navigation">
          <a href={`${sectionPrefix}#why`}>Why Forge</a>
          <a href={`${sectionPrefix}#features`}>Features</a>
          <a href={`${sectionPrefix}#workflows`}>Workflows</a>
          <Link href="/blog">Blog</Link>
          <WaitlistTrigger
            className="nav-cta nav-cta-button"
            label="Join Waitlist"
          />
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
