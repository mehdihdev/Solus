import WaitlistForm from "./waitlist-form";

export default function CtaSection() {
  return (
    <section id="cta" className="ln-reveal ln-cta">
      <h2 className="ln-cta-h2">Stop debugging in five tabs.</h2>
      <p className="ln-cta-sub">
        Be first in line when Solus opens up. Leave your email and we&apos;ll
        reach out with early access.
      </p>
      <WaitlistForm variant="cta" />
    </section>
  );
}
