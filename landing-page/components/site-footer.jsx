import Link from "next/link";

const footerLinks = [
  { href: "#why", label: "Why Forge" },
  { href: "#features", label: "Features" },
  { href: "#workflows", label: "Workflows" },
  { href: "/blog", label: "Blog", isRoute: true },
  { href: "#", label: "Privacy" },
  { href: "#", label: "Terms" },
  { href: "#", label: "Contact" },
];

export default function SiteFooter({ isHome = false }) {
  const sectionPrefix = isHome ? "" : "/";

  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div className="footer-top">
          <p className="footer-tagline">
            The robotics development environment
            <br />
            built for real-world complexity.
          </p>
          <div className="footer-links">
            {footerLinks.map((link) =>
              link.isRoute ? (
                <Link href={link.href} className="footer-link" key={link.label}>
                  {link.label}
                </Link>
              ) : (
                <a
                  href={
                    link.href.startsWith("#") && link.href.length > 1
                      ? `${sectionPrefix}${link.href}`
                      : link.href
                  }
                  className="footer-link"
                  key={link.label}
                >
                  {link.label}
                </a>
              ),
            )}
          </div>
        </div>
        <div className="footer-bottom">
          <span className="footer-copy">© 2026 Solus</span>
        </div>
      </div>
    </footer>
  );
}
