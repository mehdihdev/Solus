// Solus — SOL rendered as an engineering hammer: mark, cursor companion, mode HUD
const { useState: useStateH, useEffect: useEffectH, useRef: useRefH } = React;

/* ============ the mark ============
   Axis-aligned: twin-drum head across the top, energy core in the hub,
   tapered shaft below. viewBox 100 × 140 (height drives `size`).      */
function SolHammer({ size = 80, energy = 60, state = "idle", style, id, onClick, title }) {
  const e = Math.max(10, Math.min(100, energy)) / 100;
  const simple = size < 32;
  const glow = 3 + 13 * e * (state === "thinking" ? 1.7 : 1);
  const spin = state === "thinking";
  const uid = useRefH("h" + Math.random().toString(36).slice(2, 8)).current;

  return (
    <div id={id} title={title} onClick={onClick} style={{ width: size, height: size, position: "relative", flexShrink: 0, cursor: onClick ? "pointer" : "inherit", ...style }}>
      <svg width={size} height={size} viewBox="0 0 120 120" style={{ display: "block", overflow: "visible" }}>
        <defs>
          <linearGradient id={uid + "drum"} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--acc)" stopOpacity="0.98" />
            <stop offset="50%" stopColor="var(--acc)" stopOpacity="0.6" />
            <stop offset="100%" stopColor="var(--acc)" stopOpacity="0.92" />
          </linearGradient>
          <linearGradient id={uid + "steel"} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--mut)" stopOpacity="0.5" />
            <stop offset="45%" stopColor="var(--tx)" stopOpacity="0.8" />
            <stop offset="100%" stopColor="var(--mut)" stopOpacity="0.4" />
          </linearGradient>
        </defs>

        {/* head halo */}
        <ellipse cx="60" cy="36" rx={54 + 8 * e} ry={30 + 6 * e} fill="var(--acc)" opacity={0.13 * e + 0.05} className="hmr-halo" style={{ filter: `blur(${size * 0.05}px)` }}></ellipse>

        {/* ---- head: twin drums ---- */}
        <rect x="14" y="16" width="30" height="40" rx="4" fill={`url(#${uid}drum)`} stroke="var(--acc)" strokeWidth={simple ? 2 : 1.3} strokeOpacity="0.85"></rect>
        <rect x="76" y="16" width="30" height="40" rx="4" fill={`url(#${uid}drum)`} stroke="var(--acc)" strokeWidth={simple ? 2 : 1.3} strokeOpacity="0.85"></rect>
        {!simple && <>
          <line x1="21" y1="18" x2="21" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.45"></line>
          <line x1="29" y1="18" x2="29" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.3"></line>
          <line x1="37" y1="18" x2="37" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.45"></line>
          <line x1="83" y1="18" x2="83" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.45"></line>
          <line x1="91" y1="18" x2="91" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.3"></line>
          <line x1="99" y1="18" x2="99" y2="54" stroke="var(--bg)" strokeWidth="1.2" opacity="0.45"></line>
        </>}
        {/* striking end caps */}
        <rect x="5" y="20" width="9" height="32" rx="3" fill="var(--acc)"></rect>
        <rect x="106" y="20" width="9" height="32" rx="3" fill="var(--acc)"></rect>

        {/* central hub */}
        <rect x="44" y="10" width="32" height="52" rx="5" fill="var(--sur2)" stroke="var(--acc)" strokeWidth={simple ? 2 : 1.5} strokeOpacity="0.8"></rect>
        {!simple && <>
          <polygon points="44,22 60,14 76,22 76,28 60,21 44,28" fill="var(--acc)" opacity="0.3"></polygon>
          <line x1="44" y1="52" x2="76" y2="52" stroke="var(--acc)" strokeWidth="1" opacity="0.45"></line>
        </>}

        {/* energy core */}
        <g className={spin ? "hmr-core-fast" : "hmr-core"} style={{ transformOrigin: "60px 36px" }}>
          <circle cx="60" cy="36" r="11" fill="var(--acc)" opacity="0.3"></circle>
          <circle cx="60" cy="36" r="7" fill="var(--acc)"></circle>
          <circle cx="57.4" cy="33.4" r="2.6" fill="#fff" opacity="0.85"></circle>
        </g>
        {!simple && <circle cx="60" cy="36" r="14" fill="none" stroke="var(--acc)" strokeWidth="1.2" opacity="0.5" strokeDasharray="4 5" className={spin ? "hmr-ring-fast" : "hmr-ring"} style={{ transformOrigin: "60px 36px" }}></circle>}

        {/* ---- shaft ---- */}
        <rect x="53" y="62" width="14" height="44" rx="3.5" fill={`url(#${uid}steel)`} stroke="var(--bd)" strokeWidth="0.9"></rect>
        {!simple && <>
          <rect x="51.5" y="72" width="17" height="4" rx="1.8" fill="var(--acc)" opacity="0.8"></rect>
          <rect x="51.5" y="83" width="17" height="4" rx="1.8" fill="var(--acc)" opacity="0.6"></rect>
          <rect x="51.5" y="94" width="17" height="4" rx="1.8" fill="var(--acc)" opacity="0.42"></rect>
        </>}
        <rect x="48" y="104" width="24" height="11" rx="3.5" fill="var(--sur2)" stroke="var(--acc)" strokeWidth={simple ? 1.8 : 1.2} strokeOpacity="0.75"></rect>
      </svg>
      <div style={{ position: "absolute", left: "50%", top: "30%", width: size * 0.42, height: size * 0.42, transform: "translate(-50%,-50%)", borderRadius: "50%", pointerEvents: "none", boxShadow: `0 0 ${glow}px color-mix(in srgb, var(--acc) 60%, transparent)` }}></div>
    </div>
  );
}

/* ============ cursor companion ============ */
function SolCompanion({ mode, energy, hidden, onClick }) {
  const wrapRef = useRefH(null);
  const dotRef = useRefH(null);
  const pos = useRefH({ x: -999, y: -999 });
  const tgt = useRefH({ x: -999, y: -999 });
  const strike = useRefH({ v: 0, a: 0 });
  const angleRef = useRefH(0);
  const follow = mode === "follow" && !hidden;

  // hide the native cursor while the hammer is acting as the pointer
  // (class + !important so descendants declaring their own cursor can't override it)
  useEffectH(() => {
    document.documentElement.classList.toggle("sol-cursor-none", follow);
    return () => { document.documentElement.classList.remove("sol-cursor-none"); };
  }, [follow]);

  const paint = (x, y, rot) => {
    if (wrapRef.current) wrapRef.current.style.transform = `translate(${x}px, ${y}px) rotate(${rot}deg) translate(-50%, -30%)`;
    if (dotRef.current) dotRef.current.style.transform = `translate(${tgt.current.x}px, ${tgt.current.y}px)`;
  };

  useEffectH(() => {
    if (!follow) return;
    let raf = null, alive = true;
    const mm = (ev) => {
      tgt.current = { x: ev.clientX, y: ev.clientY };
      if (pos.current.x < -900) pos.current = { x: ev.clientX, y: ev.clientY };
      // direct write — keeps tracking correct even if rAF is throttled
      paint(pos.current.x, pos.current.y, 26 + angleRef.current + strike.current.a);
    };
    const md = () => { strike.current.v = -13; };
    const step = () => {
      if (!alive) return;
      const p = pos.current, t = tgt.current;
      if (t.x > -900) {
        if (p.x < -900) { p.x = t.x; p.y = t.y; }
        const dx = t.x - p.x;
        p.x += dx * 0.22; p.y += (t.y - p.y) * 0.22;
        const s = strike.current;
        s.v += -s.a * 0.28 - s.v * 0.18; s.a += s.v;
        const lag = Math.max(-34, Math.min(34, dx * 0.55));
        angleRef.current += (lag - angleRef.current) * 0.18;
        paint(p.x, p.y, 26 + angleRef.current + s.a);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    window.addEventListener("mousemove", mm);
    window.addEventListener("mousedown", md);
    return () => { alive = false; if (raf) cancelAnimationFrame(raf); window.removeEventListener("mousemove", mm); window.removeEventListener("mousedown", md); };
  }, [follow]);

  if (hidden) return null;

  // corner mode: pure CSS placement, no JS required
  if (mode !== "follow") {
    return (
      <div style={{ position: "fixed", right: 20, bottom: 20, zIndex: 200 }}>
        <div className="hmr-bob" style={{ cursor: "pointer" }} onClick={onClick} title="Ask SOL">
          <SolHammer size={56} energy={energy} state="idle" />
        </div>
      </div>
    );
  }

  return (
    <>
      {/* precision pointer dot — keeps clicking accurate while the hammer swings */}
      <div ref={dotRef} style={{ position: "fixed", left: 0, top: 0, zIndex: 201, pointerEvents: "none", width: 0, height: 0, transform: "translate(-999px,-999px)" }}>
        <span style={{ position: "absolute", left: -2.5, top: -2.5, width: 5, height: 5, borderRadius: 99, background: "var(--acc)", boxShadow: "0 0 7px var(--acc)" }}></span>
      </div>
      <div ref={wrapRef} style={{ position: "fixed", left: 0, top: 0, zIndex: 200, pointerEvents: "none", willChange: "transform", transform: "translate(-999px,-999px)" }}>
        <SolHammer size={62} energy={energy} state="idle" />
      </div>
    </>
  );
}

/* ============ mode HUD ============ */
function ModeHud({ show, mode }) {
  if (!show) return null;
  const follow = mode === "follow";
  return (
    <div className="toast-in" style={{ position: "fixed", bottom: 26, left: "50%", transform: "translateX(-50%)", zIndex: 205, pointerEvents: "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, background: "color-mix(in srgb, var(--sur) 94%, transparent)", border: "1px solid color-mix(in srgb, var(--acc) 45%, var(--bd))", borderRadius: 99, padding: "8px 16px 8px 10px", boxShadow: "0 12px 40px rgba(0,0,0,0.5)", backdropFilter: "blur(8px)" }}>
        <SolHammer size={26} energy={70} />
        <div>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--tx)" }}>{follow ? "Guide mode" : "Corner mode"}</div>
          <div style={{ fontSize: 10.5, color: "var(--mut)" }}>{follow ? "SOL rides your cursor" : "SOL docked bottom-right"}</div>
        </div>
        <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--mut)", border: "1px solid var(--bd)", borderRadius: 4, padding: "3px 7px", marginLeft: 4 }}>CTRL</span>
      </div>
    </div>
  );
}

Object.assign(window, { SolHammer, SolCompanion, ModeHud });
