// Keyframe CSS for the Context Model canvas — hot-edge dash flow and alert
// orb pulse — ported from the <style> block in TestDesign/Solus Prototype.html.
// Injected by GraphScreen so the graph feature stays self-contained.
export const GRAPH_MOTION_CSS = `
@keyframes gmFlow { to { stroke-dashoffset: -22; } }
.gm-flow { animation: gmFlow 1.6s linear infinite; }
@keyframes gmOrb { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.18); opacity: 0.75; } }
.gm-orb { animation: gmOrb 1.8s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .gm-flow, .gm-orb { animation: none; }
}
`
