import SolusMark from "./solus-mark";

const navLinks = [
  { href: "#how", label: "How it works" },
  { href: "#sol", label: "SOL" },
  { href: "#store", label: "Store" },
  { href: "#pricing", label: "Pricing" },
];

export default function LandingNav() {
  return (
    <nav className="ln-nav" aria-label="Primary navigation">
      <div className="ln-brand">
        <SolusMark size={26} />
        <span className="ln-brand-name">Solus</span>
      </div>
      <div className="ln-spacer" />
      {navLinks.map((link) => (
        <a href={link.href} className="ln-nav-link" key={link.href}>
          {link.label}
        </a>
      ))}
      <a href="#cta" className="ln-nav-cta">
        Join the waitlist
      </a>
    </nav>
  );
}
