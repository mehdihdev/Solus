// Solus — shared UI primitives + icons. Exports to window at bottom.
const { useState, useEffect, useRef, useCallback } = React;

/* ---------- icons (geometric, stroke=currentColor) ---------- */
const ic = (vb, inner, size = 17) => (props) => (
  <svg width={props && props.size || size} height={props && props.size || size} viewBox={vb}
    style={props && props.style} dangerouslySetInnerHTML={{ __html: inner }}></svg>
);
const SI = {
  graph: ic("0 0 17 17", '<circle cx="4" cy="4" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="13" cy="6" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="7" cy="13" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6 5l4.8.8M5.8 11.2L11.8 8" stroke="currentColor" stroke-width="1.2"/>'),
  bench: ic("0 0 17 17", '<path d="M1 9h3l2-5 3 9 2-4h5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'),
  sol: ic("0 0 17 17", '<circle cx="8.5" cy="8.5" r="4" fill="currentColor" opacity="0.85"/><circle cx="8.5" cy="8.5" r="7" fill="none" stroke="currentColor" stroke-width="1" opacity="0.4"/>'),
  team: ic("0 0 17 17", '<circle cx="6" cy="6" r="2.6" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="11.5" cy="7.5" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2 14c.5-2.5 2-3.8 4-3.8s3.5 1.3 4 3.8M10 13.5c.3-1.8 1.4-2.8 2.8-2.8 1 0 1.9.5 2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>'),
  gear: ic("0 0 17 17", '<circle cx="8.5" cy="8.5" r="2.5" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8.5" cy="8.5" r="5.8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.8 2.4"/>'),
  bell: ic("0 0 17 17", '<path d="M8.5 2a4.2 4.2 0 014.2 4.2c0 3 .9 4.3 1.8 5H2.5c.9-.7 1.8-2 1.8-5A4.2 4.2 0 018.5 2zM7 13.5a1.6 1.6 0 003 0" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'),
  x: ic("0 0 17 17", '<path d="M4 4l9 9M13 4l-9 9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'),
  check: ic("0 0 17 17", '<path d="M3 9l4 4 7-8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'),
  warn: ic("0 0 17 17", '<path d="M8.5 2.2L15.6 14H1.4L8.5 2.2z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8.5 7v3.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8.5" cy="12.2" r="0.8" fill="currentColor"/>'),
  arrowR: ic("0 0 17 17", '<path d="M3 8.5h10M9.5 4.5l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'),
  arrowL: ic("0 0 17 17", '<path d="M14 8.5H4M7.5 4.5l-4 4 4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'),
  plus: ic("0 0 17 17", '<path d="M8.5 3v11M3 8.5h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'),
  file: ic("0 0 17 17", '<path d="M4 1.8h6l3.2 3.2v10.2H4V1.8z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M10 1.8V5h3.2" fill="none" stroke="currentColor" stroke-width="1.2"/>'),
  chip2: ic("0 0 17 17", '<rect x="4.5" y="4.5" width="8" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6.5 4.5v-2.3M10.5 4.5V2.2M6.5 14.8v-2.3M10.5 14.8v-2.3M4.5 6.5H2.2M4.5 10.5H2.2M14.8 6.5h-2.3M14.8 10.5h-2.3" stroke="currentColor" stroke-width="1.1"/>'),
  play: ic("0 0 17 17", '<path d="M5 3.5l8 5-8 5v-10z" fill="currentColor"/>'),
  pause: ic("0 0 17 17", '<path d="M5.5 3.5v10M11.5 3.5v10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  search: ic("0 0 17 17", '<circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M10.5 10.5L15 15" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'),
  github: ic("0 0 17 17", '<circle cx="8.5" cy="8.5" r="6.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6 14.5v-2.2c0-.6.2-1 .5-1.3-1.7-.3-3-1.1-3-3.1 0-.9.3-1.5.8-2-.1-.3-.3-1.1.1-2 0 0 .7-.2 2.1.8a6.7 6.7 0 013.1 0c1.4-1 2.1-.8 2.1-.8.4.9.2 1.7.1 2 .5.5.8 1.1.8 2 0 2-1.3 2.8-3 3.1.3.3.5.8.5 1.4v2.1" fill="none" stroke="currentColor" stroke-width="1.1"/>'),
  spark: ic("0 0 17 17", '<path d="M9.5 1.5L4 9.5h4L7 15.5l6-8.5H8.5l1-5.5z" fill="currentColor"/>'),
  link: ic("0 0 17 17", '<path d="M7 10l3-3M5.5 8L3.8 9.7a2.6 2.6 0 003.6 3.6L9 11.6M11.5 9l1.7-1.7a2.6 2.6 0 00-3.6-3.6L8 5.4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>'),
  box: ic("0 0 17 17", '<path d="M8.5 1.8l6 3.2v7l-6 3.2-6-3.2v-7l6-3.2z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M2.5 5l6 3.2 6-3.2M8.5 8.2v7" fill="none" stroke="currentColor" stroke-width="1.1"/>'),
};

/* ---------- primitives ---------- */
function Btn({ kind = "ghost", size = "md", onClick, children, style, disabled, id }) {
  const base = {
    fontFamily: "var(--ui)", fontWeight: kind === "primary" ? 600 : 500,
    fontSize: size === "sm" ? 12 : size === "lg" ? 14.5 : 13,
    padding: size === "sm" ? "6px 12px" : size === "lg" ? "12px 22px" : "8px 15px",
    borderRadius: 3, cursor: disabled ? "default" : "pointer",
    display: "inline-flex", alignItems: "center", gap: 7, justifyContent: "center",
    transition: "background 0.12s, border-color 0.12s, opacity 0.12s",
    opacity: disabled ? 0.45 : 1, whiteSpace: "nowrap",
  };
  const kinds = {
    primary: { background: "var(--acc)", color: "var(--acc-ink)", border: "1px solid transparent" },
    ghost: { background: "transparent", color: "var(--tx)", border: "1px solid var(--bd)" },
    soft: { background: "var(--sur2)", color: "var(--tx)", border: "1px solid var(--bd)" },
    danger: { background: "transparent", color: "var(--err)", border: "1px solid var(--err)" },
    bare: { background: "transparent", color: "var(--mut)", border: "1px solid transparent" },
  };
  return (
    <button id={id} className={"sbtn sbtn-" + kind} disabled={disabled} onClick={disabled ? undefined : onClick}
      style={{ ...base, ...kinds[kind], ...style }}>{children}</button>
  );
}

function Mono({ children, size = 10, color = "var(--mut)", ls = "0.1em", style }) {
  return <span style={{ fontFamily: "var(--mono)", fontSize: size, letterSpacing: ls, color, textTransform: "uppercase", ...style }}>{children}</span>;
}

function DomainChip({ d, on = true, onClick, small }) {
  const c = dcol(d);
  return (
    <span onClick={onClick} style={{
      fontFamily: "var(--mono)", fontSize: small ? 9 : 10, letterSpacing: "0.05em",
      padding: small ? "3px 8px" : "5px 10px", borderRadius: 99, cursor: onClick ? "pointer" : "default",
      color: on ? c : "var(--mut)", background: on ? "color-mix(in srgb, " + ("var(" + SolusDomains[d].varName + ")") + " 9%, transparent)" : "transparent",
      border: `1px solid ${on ? "color-mix(in srgb, var(" + SolusDomains[d].varName + ") 30%, transparent)" : "var(--bd)"}`,
      display: "inline-flex", alignItems: "center", gap: 6, userSelect: "none", whiteSpace: "nowrap",
    }}>
      <span style={{ width: 5, height: 5, borderRadius: 99, background: on ? c : "var(--mut)", display: "inline-block" }}></span>
      {SolusDomains[d].label}
    </span>
  );
}

function Card({ children, style, pad = 16, onClick, id }) {
  return <div id={id} onClick={onClick} style={{ background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 4, padding: pad, boxSizing: "border-box", ...style }}>{children}</div>;
}

function KV({ k, v, vColor }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", borderBottom: "1px solid var(--bd)" }}>
      <span style={{ fontSize: 11.5, color: "var(--mut)", flexShrink: 0 }}>{k}</span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: vColor || "var(--tx)", textAlign: "right", whiteSpace: "nowrap" }}>{v}</span>
    </div>
  );
}

const AV_HUES = { P: 210, M: 28, J: 150, A: 285, S: 0, R: 180, K: 60 };
function Avatar({ name, size = 26 }) {
  const init = name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const hue = AV_HUES[init[0]] != null ? AV_HUES[init[0]] : (init.charCodeAt(0) * 47) % 360;
  return (
    <span style={{
      width: size, height: size, borderRadius: 99, flexShrink: 0,
      background: `oklch(0.35 0.06 ${hue})`, border: "1px solid var(--bd)",
      color: `oklch(0.85 0.06 ${hue})`, fontSize: size * 0.38, fontWeight: 600,
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--ui)",
    }}>{init}</span>
  );
}

/* sparkline: values[] normalized to its own min/max; optional warnIdx after which stroke turns err */
function Spark({ values, w = 120, h = 30, color = "var(--acc)", fill = true, yMin, yMax }) {
  if (!values || values.length < 2) return <svg width={w} height={h}></svg>;
  const mn = yMin != null ? yMin : Math.min(...values);
  const mx = yMax != null ? yMax : Math.max(...values);
  const rg = mx - mn || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - mn) / rg) * (h - 4)}`);
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      {fill && <polygon points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={color} opacity="0.10"></polygon>}
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round"></polyline>
    </svg>
  );
}

function Spinner({ size = 14, color = "var(--acc)" }) {
  return <span className="sol-spin" style={{ width: size, height: size, border: `1.6px solid var(--bd)`, borderTopColor: color, borderRadius: 99, display: "inline-block", flexShrink: 0 }}></span>;
}

function useInterval(fn, ms, on = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!on || ms == null) return;
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms, on]);
}

/* segmented control */
function Seg({ options, value, onChange, size = "md", ids }) {
  return (
    <div style={{ display: "inline-flex", background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: 3, overflow: "hidden" }}>
      {options.map((o, i) => (
        <span key={o} id={ids && ids[i]} onClick={() => onChange(o)} style={{
          fontSize: size === "sm" ? 11 : 12.5, fontWeight: 500, padding: size === "sm" ? "5px 11px" : "6px 14px",
          cursor: "pointer", userSelect: "none",
          background: value === o ? "var(--sur2)" : "transparent",
          color: value === o ? "var(--tx)" : "var(--mut)",
          borderRight: i < options.length - 1 ? "1px solid var(--bd)" : "none",
          boxShadow: value === o ? "inset 0 -2px 0 var(--acc)" : "none",
        }}>{o}</span>
      ))}
    </div>
  );
}

Object.assign(window, { SI, Btn, Mono, DomainChip, Card, KV, Avatar, Spark, Spinner, useInterval, Seg });
