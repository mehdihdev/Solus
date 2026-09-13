import VerifiedSeal from "./verified-seal";

const extensions = [
  {
    icon: "∿",
    name: "Live Signals",
    description: "Every telemetry stream as a widget with anomaly markers.",
    isFirstParty: true,
  },
  {
    icon: "✓",
    name: "FSAE Rules Checker",
    description: "EV rules checked against your CAD and schematic.",
    isFirstParty: false,
  },
  {
    icon: "◇",
    name: "Servo Tuner",
    description: "Interactive PID tuning against sim or live hardware.",
    isFirstParty: false,
  },
  {
    icon: "≡",
    name: "Datasheet Finder",
    description: "Part datasheets pinned to your graph nodes.",
    isFirstParty: false,
  },
];

function badgeStyle(isFirstParty) {
  return {
    borderColor: isFirstParty ? "#2a4a30" : "#3a4354",
    color: isFirstParty ? "#7fd494" : "#8b95a5",
  };
}

export default function StoreSection() {
  return (
    <section id="store" className="ln-reveal ln-section">
      <div className="ln-store-head">
        <div>
          <div className="ln-eyebrow">THE STORE</div>
          <h2 className="ln-h2">
            Every robot is different. Make Solus match yours.
          </h2>
          <p className="ln-store-sub">
            Install exactly the capabilities your build needs: telemetry
            widgets, rules checkers, tuning tools, part lookups. From verified
            first-party extensions or the community.
          </p>
        </div>
        <span className="ln-store-verified">
          SOLUS VERIFIED
          <VerifiedSeal size={13} />
        </span>
      </div>

      <div className="ln-store-grid">
        {extensions.map((extension) => (
          <article className="ln-card ln-store-card" key={extension.name}>
            <span className="ln-store-icon">{extension.icon}</span>
            <div className="ln-store-name">{extension.name}</div>
            <div className="ln-store-desc">{extension.description}</div>
            <span
              className="ln-store-badge"
              style={badgeStyle(extension.isFirstParty)}
            >
              {extension.isFirstParty ? "SOLUS" : "COMMUNITY"}
              <VerifiedSeal
                size={12}
                style={{
                  display: extension.isFirstParty ? "block" : "none",
                  flexShrink: 0,
                }}
              />
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}
