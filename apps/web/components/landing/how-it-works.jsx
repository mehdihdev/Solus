import CyclingWord from "./cycling-word";

const steps = [
  {
    number: "01",
    title: "Connect your tools",
    body: "GitHub, Onshape, KiCad, serial devices, simulators. Each source syncs into one graph — entities, relations, provenance.",
  },
  {
    number: "02",
    title: "See the whole system",
    body: "The context model links a line of firmware to the pin it drives to the bracket it moves. Live telemetry lands on the same nodes.",
  },
  {
    number: "03",
    title: "Ask SOL to explain it",
    body: "The agent reasons across domains, cites the graph, and queues fixes for approval — it never writes to hardware directly.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how" className="ln-reveal ln-section">
      <div className="ln-eyebrow">HOW IT WORKS</div>
      <h2 className="ln-h2 ln-how-h2">
        <CyclingWord /> problems are never in one file.
      </h2>
      <p className="ln-how-sub">
        A stall lives between a Python policy, a URDF limit, and a servo&apos;s
        current draw. Solus keeps those links so nobody has to hold them in
        their head.
      </p>

      <div className="ln-how-grid">
        {steps.map((step) => (
          <article className="ln-card ln-how-card" key={step.number}>
            <div className="ln-how-num">{step.number}</div>
            <div className="ln-how-title">{step.title}</div>
            <div className="ln-how-body">{step.body}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
