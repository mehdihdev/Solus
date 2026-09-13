import SolusMark from "./solus-mark";

const footerLinks = [
  { href: "#", label: "Privacy" },
  { href: "#", label: "Terms" },
  { href: "#", label: "Docs" },
  { href: "#", label: "GitHub ↗" },
];

export default function LandingFooter() {
  return (
    <footer className="ln-footer">
      <div className="ln-brand">
        <SolusMark size={18} />
        <span className="ln-footer-name">Solus</span>
      </div>
      <span className="ln-footer-copy">© 2026 Solus Robotics, Inc.</span>
      <div className="ln-spacer" />
      {footerLinks.map((link) => (
        <a href={link.href} className="ln-footer-link" key={link.label}>
          {link.label}
        </a>
      ))}
    </footer>
  );
}
