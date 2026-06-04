import PageAnimations from "../components/page-animations";
import HeroActions from "../components/hero-actions";
import SiteFooter from "../components/site-footer";
import SiteHeader from "../components/site-header";
import WaitlistTrigger from "../components/waitlist-trigger";

const whyItems = [
  {
    number: "01",
    title: "Unified context",
    description:
      "Manage BOMs, control systems, simulations, and code from one shared workspace so the entire robot pipeline stays aligned.",
  },
  {
    number: "02",
    title: "Portable environments",
    description:
      "Carry project state, dependencies, and simulation setup across machines, teams, and deployment targets without fragile scripts.",
  },
  {
    number: "03",
    title: "Domain-aware pipelines",
    description:
      "Link mechanical design changes to electrical validation and software simulation in a single workflow that updates automatically.",
  },
  {
    number: "04",
    title: "Ship faster",
    description:
      "Remove environment setup chaos so engineers spend less time bootstrapping and more time shipping robust robotic systems.",
  },
];

const stats = [
  { value: "4×", label: "faster onboarding" },
  { value: "1 unified", label: "workspace" },
  { value: "100%", label: "context retained" },
  { value: "4", label: "domains, one tool" },
];

const features = [
  {
    number: "01",
    title: "Context portability",
    description:
      "Carry project state, dependencies, and simulation setup across machines, teams, and deployment targets without fragile scripts.",
  },
  {
    number: "02",
    title: "Domain-aware pipelines",
    description:
      "Link mechanical design changes to electrical validation and software simulation in a single workflow that updates automatically.",
  },
  {
    number: "03",
    title: "Real-world validation",
    description:
      "Run realistic simulation scenarios directly from Forge, then push validated configurations into production-ready build assets.",
  },
  {
    number: "04",
    title: "Faster team delivery",
    description:
      "Remove environment setup chaos so engineers spend less time bootstrapping and more time shipping robust robotic systems.",
  },
];

const workflowBullets = [
  "Shared engineering projects that include CAD, circuits, code, and virtual tests",
  "Portable environments that preserve configuration, dependencies, and simulation data",
  "Automated workspaces that update as the robot design evolves",
];

const workflowSteps = [
  {
    number: "01",
    title: "Define the robot project",
    description:
      "Import BOMs, mechanical assemblies, firmware, and test cases into one consistent workspace.",
  },
  {
    number: "02",
    title: "Sync domain data",
    description:
      "Keep electrical, mechanical, and simulation context aligned as the design changes.",
  },
  {
    number: "03",
    title: "Validate and ship",
    description:
      "Validate systems in simulation, share portable artifacts, and ship robotic systems faster.",
  },
];

const sidebarProjects = ["bipedal-v3.2", "arm-assembly", "sensor-stack"];

const sidebarDomains = [
  { name: "Mechanical", color: "green" },
  { name: "Electrical", color: "cyan" },
  { name: "Software", color: "blue" },
  { name: "Simulation", color: "purple" },
];

const domainPanels = [
  {
    name: "Mechanical",
    status: "Active",
    color: "green",
    files: [
      "BOM_rev4.xml",
      "chassis_assembly.step",
      "joint_constraints.json",
      "tolerance_spec.pdf",
    ],
    meta: "Rev D · 14 components",
  },
  {
    name: "Electrical",
    status: "Synced",
    color: "cyan",
    files: [
      "schematic_rev4.kicad",
      "power_rails.json",
      "sensor_map.yaml",
      "pcb_layout.kicad_pcb",
    ],
    meta: "Rev D · 8 boards",
  },
  {
    name: "Software",
    status: "Live",
    color: "blue",
    files: [
      "main.rs @ a3f9c2d",
      "ros2_config.toml",
      "motion_controller.py",
      "test_suite.yaml",
    ],
    meta: "main · 3 contributors",
  },
  {
    name: "Simulation",
    status: "Ready",
    color: "purple",
    files: [
      "world_v3.urdf",
      "physics_params.cfg",
      "gait_scenarios.yaml",
      "collision_mesh.obj",
    ],
    meta: "ROS 2 Humble · 6 tests",
  },
];

const terminalLines = [
  { content: "forge sync --all", prompt: true },
  { content: "Mechanical context loaded (rev4)", tone: "ok" },
  { content: "Electrical schematics synced", tone: "ok" },
  { content: "Software pinned to a3f9c2d", tone: "ok" },
  { content: "Simulation environment ready", tone: "ok" },
  { content: "Context is portable. Ready to build.", tone: "dim" },
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
            <p className="hero-label">Forge RDE — Robotics Development Environment</p>
            <h1>
              <RevealLines
                lines={[
                  "The robotics",
                  "development",
                  "environment",
                  "built for real-world",
                  "complexity.",
                ]}
              />
            </h1>
            <div className="hero-sub-row">
              <p className="hero-desc">
                Forge is our RDE: a unified workspace for mechanical,
                electrical, software, and simulation context. We remove
                environment setup chaos, make context portable, and help
                robotics teams ship faster.
              </p>
              <HeroActions />
            </div>
          </div>

          <div className="forge-mockup-wrap" id="demo">
            <div className="forge-mockup">
              <div className="mockup-bar">
                <div className="mockup-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <span className="mockup-title">
                  forge — bipedal-v3.2 — all domains synced
                </span>
                <span className="mockup-badge">● live</span>
              </div>
              <div className="mockup-body">
                <div className="mockup-sidebar">
                  <div className="sb-section">
                    <div className="sb-label">Project</div>
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
                      <div className="sb-item active" key={domain.name}>
                        <span className={`dot ${domain.color}`} />
                        {domain.name}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mockup-main">
                  <div className="domain-grid">
                    {domainPanels.map((panel) => (
                      <div className="domain-panel" key={panel.name}>
                        <div className="domain-head">
                          <span className="domain-name">{panel.name}</span>
                          <span className={`domain-tag ${panel.color}`}>
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

                  <div className="mockup-terminal">
                    {terminalLines.map((line) => (
                      <div
                        className={`term-line${line.tone ? ` ${line.tone}` : ""}`}
                        key={line.content}
                      >
                        {line.prompt ? (
                          <>
                            <span className="term-prompt">$</span>
                            {line.content}
                          </>
                        ) : (
                          <>
                            {line.tone === "ok" ? "✓ " : "→ "}
                            {line.content}
                          </>
                        )}
                      </div>
                    ))}
                    <div className="term-cursor" aria-hidden="true">
                      █
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow" />
        </div>

        <section id="why" className="section-why">
          <div className="container">
            <div className="why-header">
              <p className="section-label" data-fade-up>
                Built for robotics teams
              </p>
              <h2 data-reveal-lines>
                <RevealLines
                  lines={[
                    "Stop fighting environments.",
                    "Start building robots.",
                  ]}
                />
              </h2>
            </div>
            <div className="why-grid" data-stagger>
              {whyItems.map((item) => (
                <div className="why-item" key={item.number}>
                  <span className="why-num">{item.number}</span>
                  <h3>{item.title}</h3>
                  <p>{item.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow pink" />
        </div>

        <section className="section-stats">
          <div className="container">
            <div className="stats-row" data-stagger>
              {stats.map((stat) => (
                <div className="stat-item" key={stat.label}>
                  <strong>{stat.value}</strong>
                  <span>{stat.label}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow" />
        </div>

        <section id="features" className="section-features">
          <div className="container">
            <div className="features-header">
              <p className="section-label" data-fade-up>
                Features
              </p>
              <h2 data-reveal-lines>
                <RevealLines
                  lines={[
                    "Everything your robotics",
                    "team needs, connected.",
                  ]}
                />
              </h2>
            </div>
            <div className="features-grid" data-stagger>
              {features.map((feature) => (
                <article className="feature-item" key={feature.number}>
                  <div className="feature-num">{feature.number}</div>
                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow pink" />
        </div>

        <section id="workflows" className="section-workflows">
          <div className="container">
            <div className="workflows-top">
              <div className="workflows-copy">
                <p className="section-label" data-fade-up>
                  How Forge works
                </p>
                <h2 data-reveal-lines>
                  <RevealLines
                    lines={[
                      "From prototype to production,",
                      "every context travels",
                      "with the robot.",
                    ]}
                  />
                </h2>
                <p data-fade-up>
                  Forge stitches together engineering domains and simulation
                  feedback into a single source of truth. Prototype faster,
                  validate earlier, deploy with confidence.
                </p>
              </div>
              <ul className="workflows-list" data-stagger>
                {workflowBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>

            <div className="workflows-steps" data-stagger>
              {workflowSteps.map((step) => (
                <div className="step" key={step.number}>
                  <div className="step-num">{step.number}</div>
                  <div className="step-body">
                    <h4>{step.title}</h4>
                    <p>{step.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="line-sep">
          <div className="line-glow" />
        </div>

        <section id="start" className="section-cta">
          <div className="container">
            <h2 data-reveal-lines>
              <RevealLines
                lines={[
                  "Ready to forge your",
                  "robotics workflow?",
                ]}
              />
            </h2>
            <div data-fade-up>
              <WaitlistTrigger label="Join the Waitlist →" variant="cta" />
            </div>
          </div>
        </section>
      </main>

      <SiteFooter isHome />
    </>
  );
}
