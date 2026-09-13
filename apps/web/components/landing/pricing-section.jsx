export default function PricingSection() {
  return (
    <section id="pricing" className="ln-reveal ln-section">
      <div className="ln-pricing-head">
        <div className="ln-eyebrow">PRICING</div>
        <h2 className="ln-h2">Start free. Pay when it earns its keep.</h2>
      </div>

      <div className="ln-pricing-grid">
        <article className="ln-card ln-plan">
          <div className="ln-plan-name">Basic</div>
          <div className="ln-plan-sub">For getting started</div>
          <div className="ln-plan-price">
            <span className="ln-plan-amount">Free</span>
          </div>
          <div className="ln-plan-features">
            All capabilities
            <br />
            2,500 credits included
            <br />3 projects · 2 teams · 4 integrations
          </div>
          <div className="ln-spacer" />
          <a href="#cta" className="ln-plan-btn">
            Join the waitlist
          </a>
        </article>

        <article className="ln-card ln-plan is-featured">
          <div className="ln-plan-head">
            <span className="ln-plan-name">Pro</span>
            <span className="ln-plan-tag">MOST POPULAR</span>
          </div>
          <div className="ln-plan-sub">For full-stack teams</div>
          <div className="ln-plan-price">
            <span className="ln-plan-amount">$50</span>
            <span className="ln-plan-per"> /month</span>
          </div>
          <div className="ln-plan-features">
            All capabilities
            <br />
            10,000 credits included
            <br />
            Unlimited projects, teams, integrations
          </div>
          <div className="ln-spacer" />
          <a href="#cta" className="ln-plan-btn is-primary">
            Join the waitlist
          </a>
        </article>

        <article className="ln-card ln-plan">
          <div className="ln-plan-name">Enterprise</div>
          <div className="ln-plan-sub">Custom limits, SSO, support</div>
          <div className="ln-plan-price is-custom">Custom pricing</div>
          <div className="ln-plan-features">
            Per-seat, set per agreement
            <br />
            Compliance packs (FSAE, UL)
            <br />
            Dedicated support
          </div>
          <div className="ln-spacer" />
          <button type="button" className="ln-plan-btn">
            Contact sales
          </button>
        </article>
      </div>
    </section>
  );
}
