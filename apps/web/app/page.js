import PageAnimations from "../components/page-animations";
import HeroActions from "../components/hero-actions";
import SiteFooter from "../components/site-footer";
import SiteHeader from "../components/site-header";
import WaitlistTrigger from "../components/waitlist-trigger";

const sidebarProjects = ["bipedal-v3.2", "arm-assembly", "sensor-stack"];

const sidebarDomains = [
  { id: "sw", name: "Software" },
  { id: "ee", name: "Electrical" },
  { id: "me", name: "Mechanical" },
  { id: "rt", name: "Runtime" },
];

const domainPanels = [
  {
    id: "sw",
    name: "Software",
    status: "Synced",
    files: [
      "motion_controller.py",
      "camera_node  (ROS 2)",
      "main.rs @ a3f9c2d",
      "ros2_config.yaml",
    ],
    meta: "GitHub · main · 3 contributors",
  },
  {
    id: "ee",
    name: "Electrical",
    status: "Rev D",
    files: [
      "pdb_rev4.kicad_sch",
      "OV9281_IC  (camera)",
      "imu_breakout.kicad_pcb",
      "power_rails.net",
    ],
    meta: "KiCad · 8 boards",
  },
  {
    id: "me",
    name: "Mechanical",
    status: "Current",
    files: [
      "chassis_v3.step",
      "CAM_v2  (mount)",
      "mast_assembly",
      "tolerance_spec.pdf",
    ],
    meta: "Onshape · 14 parts",
  },
  {
    id: "rt",
    name: "Runtime",
    status: "Live",
    files: [
      "/imu/data · 200 Hz",
      "/camera/image_raw · 30 fps",
      "battery_bus · 11.9 V",
      "/joint_states",
    ],
    meta: "Live Bench · streaming",
  },
];

const solLines = [
  {
    tone: "warn",
    content:
      "I2C address conflict: IMU (0x68) and ToF sensor (0x68) share bus 1 — caught in schematic rev D, before flash.",
  },
  {
    tone: "ok",
    content:
      "camera_node ↔ OV9281_IC ↔ CAM_v2 linked across ROS, KiCad, and Onshape (fingerprint confidence 0.94).",
  },
  {
    tone: "dim",
    content: "31 checks passed · 1 warning · graph updated 2 m ago",
  },
];

const howSteps = [
  {
    number: "01",
    title: "Connect your tools",
    description:
      "Link GitHub, KiCad, Onshape, and ROS. Connectors translate each tool into shared entities and relations — no changes to how your team already works.",
  },
  {
    number: "02",
    title: "One living graph",
    description:
      "Every code module, IC, CAD part, and telemetry signal becomes a node in one graph of your robot. It stays current as the design changes, in every domain.",
  },
  {
    number: "03",
    title: "Catch breaks early",
    description:
      "Checkers and the SOL agent reason across domains — pin conflicts, power budgets, mismatched interfaces — and flag problems before they break hardware.",
  },
];

function RevealLines({ lines }) {
  return lines.map((line) => (
    <span className="rl" key={line}>
      <span>{line}</span>
    </span>
  ));
}

export default function HomePage() {
  return (
    <>
      <PageAnimations />
      <SiteHeader isHome />

      <main>
        <section className="hero">
          <div className="container">
            <p className="hero-label">Solus — the robotics context layer</p>
            <h1>
              <RevealLines
                lines={[
                  "Your robot lives",
                  "in four worlds.",
                  "Solus makes them one.",
                ]}
              />
            </h1>
            <div className="hero-sub-row">
              <p className="hero-desc">
                Code, electronics, CAD, and the running robot drift apart until
                something fails. Solus connects GitHub, KiCad, Onshape, and ROS
                into one living graph — and catches cross-domain problems before
                they break hardware.
              </p>
              <HeroActions />
            </div>
          </div>

          <div className="product-mockup-wrap" id="demo">
            <div className="product-mockup">
              <div className="mockup-bar">
                <div className="mockup-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <span className="mockup-title">
                  solus — bipedal-v3.2 — 4 domains · 1 graph
                </span>
                <span className="mockup-badge">● synced</span>
              </div>
              <div className="mockup-body">
                <div className="mockup-sidebar">
                  <div className="sb-section">
                    <div className="sb-label">Projects</div>
                    {sidebarProjects.map((project, index) => (
                      <div
                        className={`sb-item${index === 0 ? " active" : ""}`}
                        key={project}
                      >
                        {project}
                      </div>
                    ))}
                  </div>
                  <div className="sb-section">
                    <div className="sb-label">Domains</div>
                    {sidebarDomains.map((domain) => (
                      <div className="sb-item active" key={domain.id}>
                        <span className={`dot ${domain.id}`} />
                        {domain.name}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mockup-main">
                  <div className="domain-grid">
                    {domainPanels.map((panel) => (
                      <div className="domain-panel" key={panel.id}>
                        <div className="domain-head">
                          <span className="domain-name">{panel.name}</span>
                          <span className={`domain-tag ${panel.id}`}>
                            {panel.status}
                          </span>
                        </div>
                        <div className="domain-files">
                          {panel.files.map((file, index) => (
                            <div
                              className={`file-row${index === 3 ? " muted" : ""}`}
                              key={file}
                            >
                              <span className="file-icon">◈</span>
                              {file}
                            </div>
                          ))}
                        </div>
                        <div className="domain-meta">{panel.meta}</div>
                      </div>
                    ))}
                  </div>

                  <div className="sol-strip">
                    <div className="sol-strip-head">
                      <span className="sol-orb pulse" aria-hidden="true" />
                      <span className="sol-strip-title">SOL · diagnosis</span>
                    </div>
                    {solLines.map((line) => (
                      <div
                        className={`sol-line ${line.tone}`}
                        key={line.content}
                      >
                        {line.content}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow" />
        </div>

        <section id="how" className="section-how">
          <div className="container">
            <p className="section-label" data-fade-up>
              How Solus works
            </p>
            <h2 data-reveal-lines>
              <RevealLines
                lines={[
                  "From four disconnected tools",
                  "to one system you can reason about.",
                ]}
              />
            </h2>
            <div className="how-grid" data-stagger>
              {howSteps.map((step) => (
                <article className="how-step" key={step.number}>
                  <div className="how-num">{step.number}</div>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow me" />
        </div>

        <section id="start" className="section-cta">
          <div className="container">
            <h2 data-reveal-lines>
              <RevealLines lines={["See your robot", "as one system."]} />
            </h2>
            <div data-fade-up>
              <WaitlistTrigger label="Join the waitlist →" variant="cta" />
            </div>
          </div>
        </section>
      </main>

      <SiteFooter isHome />
    </>
  );
}
