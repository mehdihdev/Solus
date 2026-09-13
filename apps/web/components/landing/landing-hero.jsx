import WaitlistForm from "./waitlist-form";

const MARQUEE_SOURCES =
  "ONSHAPE · GITHUB · KICAD · ALTIUM · MUJOCO · GAZEBO · ISAAC SIM · GITLAB · FUSION · ";

export default function LandingHero() {
  return (
    <section className="ln-hero">
      <div className="ln-hero-badge">
        <span className="ln-hero-badge-dot" aria-hidden="true" />
        Now in beta
      </div>

      <h1 className="ln-hero-h1">
        The Greatest Robotics Tool You Could Ever Have
      </h1>

      <p className="ln-hero-sub">
        Solus links your repos, CAD files, schematics, and live telemetry into a
        single multimodal context - so that you, your team, and your agents get
        to work on what&apos;s actually important.
      </p>

      <div className="ln-hero-form-row">
        <WaitlistForm variant="hero" />
      </div>

      <div className="ln-marquee">
        <div className="ln-marquee-track" aria-hidden="true">
          <span>{MARQUEE_SOURCES}</span>
          <span>{MARQUEE_SOURCES}</span>
        </div>
        <div className="ln-marquee-mask" />
      </div>
    </section>
  );
}
