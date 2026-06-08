import WaitlistTrigger from "./waitlist-trigger";

export default function HeroActions() {
  return (
    <div className="hero-actions">
      <WaitlistTrigger label="Join the waitlist →" variant="cta" />
      <a
        href="https://youtu.be/qszQ76kajuM"
        target="_blank"
        rel="noreferrer"
        className="link-plain waitlist-trigger"
      >
        Watch the walkthrough
      </a>
    </div>
  );
}
