import Link from "next/link";
import ThemeToggle from "./theme-toggle";
import WaitlistTrigger from "./waitlist-trigger";

export default function SiteHeader({ isHome = false }) {
  const sectionPrefix = isHome ? "" : "/";

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link href="/" className="wordmark">
          <span className="sol-orb" aria-hidden="true" />
          SOLUS
        </Link>
        <nav className="site-nav" aria-label="Primary navigation">
          <a href={`${sectionPrefix}#demo`}>Product</a>
          <a href={`${sectionPrefix}#how`}>How it works</a>
          <Link href="/blog">Blog</Link>
          <WaitlistTrigger className="nav-cta-button" label="Join Waitlist" />
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
