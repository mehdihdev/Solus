// Solus — theme presets + domain colors + applyTheme
window.SolusThemes = {
  dark: {
    name: "Solus Dark",
    bg: "#0A0C0F", sur: "#10131A", sur2: "#161B23", bd: "#222834",
    tx: "#E6E9EE", mut: "#828B99",
    ok: "#5BCD8C", warn: "#E5A43B", err: "#E0564D",
    sw: "#62A9FF", ee: "#E3C25B", me: "#E87FAE", rt: "#5BCD8C",
  },
  light: {
    name: "Solus Light",
    bg: "#F2F3F5", sur: "#FFFFFF", sur2: "#EAECEF", bd: "#D7DBE2",
    tx: "#1A1E26", mut: "#5E6878",
    ok: "#1F8A55", warn: "#A87514", err: "#C6453C",
    sw: "#2C6FD6", ee: "#A87514", me: "#C2487F", rt: "#1F8A55",
  },
  dkplus: {
    name: "Editor · Dark+",
    bg: "#1B1B1C", sur: "#222223", sur2: "#2A2A2C", bd: "#3C3C40",
    tx: "#D6D6D6", mut: "#8C8C8C",
    ok: "#4EC9B0", warn: "#DCDCAA", err: "#F47067",
    sw: "#569CD6", ee: "#DCDCAA", me: "#C586C0", rt: "#4EC9B0",
  },
  monokai: {
    name: "Editor · Monokai",
    bg: "#26271F", sur: "#2D2E26", sur2: "#36372E", bd: "#4A4940",
    tx: "#F8F8F2", mut: "#94927F",
    ok: "#A6E22E", warn: "#E6DB74", err: "#F92672",
    sw: "#66D9EF", ee: "#E6DB74", me: "#F92672", rt: "#A6E22E",
  },
  solarized: {
    name: "Editor · Solarized",
    bg: "#002B36", sur: "#06333F", sur2: "#0C3D4A", bd: "#1A5260",
    tx: "#E2DBC6", mut: "#7E959E",
    ok: "#859900", warn: "#B58900", err: "#DC322F",
    sw: "#268BD2", ee: "#B58900", me: "#D33682", rt: "#859900",
  },
};

window.SolusAccents = {
  amber:  { c: "#E5A43B", ink: "#0A0C0F" },
  teal:   { c: "#50D0B4", ink: "#0B1612" },
  blue:   { c: "#62A9FF", ink: "#0A1018" },
  violet: { c: "#B98BEA", ink: "#161019" },
};

window.applySolusTheme = function (themeId, accentId, density) {
  const t = window.SolusThemes[themeId] || window.SolusThemes.dark;
  const a = window.SolusAccents[accentId] || window.SolusAccents.amber;
  const r = document.documentElement;
  const map = {
    "--bg": t.bg, "--sur": t.sur, "--sur2": t.sur2, "--bd": t.bd,
    "--tx": t.tx, "--mut": t.mut, "--ok": t.ok, "--warn": t.warn, "--err": t.err,
    "--sw": t.sw, "--ee": t.ee, "--me": t.me, "--rt": t.rt,
    "--acc": a.c, "--acc-ink": a.ink,
  };
  Object.keys(map).forEach((k) => r.style.setProperty(k, map[k]));
  r.setAttribute("data-theme", themeId);
  r.setAttribute("data-density", density || "regular");
  document.body.style.background = t.bg;
};

window.SolusDomains = {
  sw: { label: "SOFTWARE", varName: "--sw" },
  ee: { label: "ELECTRICAL", varName: "--ee" },
  me: { label: "MECHANICAL", varName: "--me" },
  rt: { label: "RUNTIME", varName: "--rt" },
};
// helper: domain color as CSS var ref
window.dcol = (d) => `var(${window.SolusDomains[d].varName})`;
