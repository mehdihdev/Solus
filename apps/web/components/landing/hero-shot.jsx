import SolusMark from "./solus-mark";

const windowDots = ["#ff5f57", "#febc2e", "#28c840"];

const nodes = [
  {
    id: "github",
    name: "GitHub",
    dot: "#4c8dff",
    meta: "act_policy.py · 4 nodes",
  },
  {
    id: "onshape",
    name: "Onshape",
    dot: "#3ddc97",
    meta: "so101 assembly · 439 entities",
  },
  { id: "mujoco", name: "MuJoCo", dot: "#3ddc97", meta: "sim · RT ×1.0" },
  {
    id: "live",
    name: "SO-101 · live",
    dot: "#f5b83d",
    meta: "joint_2 · 3.0 A stall",
  },
];

export default function HeroShot() {
  return (
    <div className="ln-shot-frame">
      <div className="ln-shot-bar">
        {windowDots.map((color) => (
          <span
            className="ln-shot-dot"
            style={{ background: color }}
            key={color}
          />
        ))}
        <span className="ln-shot-chip">
          <svg
            width="11"
            height="11"
            viewBox="0 0 20 20"
            fill="none"
            stroke="#f5b83d"
            strokeWidth="1.7"
            aria-hidden="true"
          >
            <rect x="4" y="7" width="12" height="9" rx="2" />
            <path d="M10 7 V3.5" />
            <circle cx="10" cy="3" r="1.4" fill="#f5b83d" stroke="none" />
          </svg>
          spot-r1 ▾
        </span>
      </div>

      <div className="ln-hero-shot">
        <div className="ln-shot-glow" />

        <svg
          className="ln-shot-wires"
          viewBox="0 0 100 400"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <line
            x1="18"
            y1="110"
            x2="49"
            y2="205"
            stroke="#232d3b"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1="75"
            y1="95"
            x2="49"
            y2="205"
            stroke="#232d3b"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1="23"
            y1="320"
            x2="49"
            y2="205"
            stroke="#232d3b"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1="46"
            y1="325"
            x2="49"
            y2="205"
            stroke="#b98a2e"
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
            strokeDasharray="8 7"
            className="ln-wire-live"
          />
        </svg>

        {nodes.map((node) => (
          <div className={`ln-node is-${node.id}`} key={node.id}>
            <div className="ln-node-head">
              <span className="ln-node-dot" style={{ background: node.dot }} />
              <span className="ln-node-name">{node.name}</span>
            </div>
            <div className="ln-node-meta">{node.meta}</div>
          </div>
        ))}

        <div className="ln-node is-graph">
          <div className="ln-node-head">
            <SolusMark size={20} />
            <span className="ln-node-name">Context graph</span>
          </div>
          <div className="ln-node-meta">2,696 entities · 2,683 relations</div>
        </div>

        <div className="ln-sol-callout">
          <div className="ln-sol-callout-head">
            <div className="ln-sol-orb" aria-hidden="true" />
            <span className="ln-sol-callout-name">SOL</span>
          </div>
          <div className="ln-sol-callout-body">
            joint_2 stalls because{" "}
            <span style={{ color: "#e0679a" }}>act_policy.py</span> commands
            104° but <span style={{ color: "#f5b83d" }}>so101.urdf</span> limits
            it to ±90°. Want me to queue a clamp fix?
          </div>
        </div>
      </div>
    </div>
  );
}
