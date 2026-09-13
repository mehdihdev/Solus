import "./landing.css";

import CtaSection from "../components/landing/cta-section";
import HeroShot from "../components/landing/hero-shot";
import HowItWorks from "../components/landing/how-it-works";
import LandingFooter from "../components/landing/landing-footer";
import LandingHero from "../components/landing/landing-hero";
import LandingNav from "../components/landing/landing-nav";
import PricingSection from "../components/landing/pricing-section";
import RevealObserver from "../components/landing/reveal-observer";
import SolSection from "../components/landing/sol-section";
import StoreSection from "../components/landing/store-section";
import { WaitlistProvider } from "../components/landing/waitlist-context";

export const metadata = {
  title: "Solus | The Greatest Robotics Tool You Could Ever Have",
  description:
    "Solus links your repos, CAD files, schematics, and live telemetry into a single multimodal context — so that you, your team, and your agents get to work on what's actually important.",
};

export default function HomePage() {
  return (
    <WaitlistProvider>
      <RevealObserver />
      <div className="ln-root">
        <div className="ln-container">
          <LandingNav />
          <LandingHero />
          <HeroShot />
          <HowItWorks />
          <SolSection />
          <StoreSection />
          <PricingSection />
          <CtaSection />
          <LandingFooter />
        </div>
      </div>
    </WaitlistProvider>
  );
}
