const claims = [
  "Diagnoses across code, CAD, and electronics",
  "Cites its sources — every claim links to the graph",
  "Proposes fixes for approval - nothing reaches your robot unasked",
];

export default function SolSection() {
  return (
    <section id="sol" className="ln-reveal ln-sol">
      <div>
        <div className="ln-eyebrow">MEET SOL</div>
        <h2 className="ln-h2">
          An agent grounded in your machine, not the internet.
        </h2>
        <p className="ln-sol-lede">
          Every answer is grounded in your connected sources and cited back to
          real entities. Guide mode teaches the tool you don&apos;t know; Expert
          mode gets out of your way.
        </p>
        <div className="ln-sol-checks">
          {claims.map((claim) => (
            <div className="ln-sol-check" key={claim}>
              <span className="ln-sol-check-mark">✓</span>
              {claim}
            </div>
          ))}
        </div>
      </div>

      <div className="ln-sol-chat">
        <div className="ln-chat-user-row">
          <div className="ln-chat-user">
            Why does the arm freeze at the top of the pick?
          </div>
        </div>
        <div className="ln-chat-tools">
          get_telemetry → ok · read so101.urdf → ok · read act_policy.py → ok
        </div>
        <div className="ln-chat-answer">
          It&apos;s a commanded-position clash, not a mechanical jam.{" "}
          <span className="ln-chat-ref">act_policy.py L214</span> outputs up to
          104° on joint_2, but <span className="ln-chat-ref">so101.urdf</span>{" "}
          caps it at ±90° — the servo hits the limit and stalls at 3.0 A. I can
          clamp the policy head and queue it for your approval.
        </div>
        <div className="ln-chat-actions">
          <span className="ln-chat-action">Queue the fix</span>
          <span className="ln-chat-action is-ghost">Show me in the graph</span>
        </div>
      </div>
    </section>
  );
}
