# Solus Landing Starter Page — Design

**Date:** 2026-08-08 · **Scope:** `apps/web` only · **Branch:** `SOLUSDEV-102-altium-mcp` (shared; per human direction, no new branch)

## Goal

Replace the "Forge RDE" landing page with a lean **starter page** that reflects the current Solus desktop product's design language, keeping the existing plumbing (waitlist API + modal, blog routes, theme toggle, GSAP/Lenis animations) so further edits iterate on a working base.

## Decisions (human-approved in-session)

1. **Rebrand to SOLUS** — wordmark + SOL orb, current product story (graph, connectors, SOL agent, Live Bench). "Forge" naming removed.
2. **Keep plumbing, replace visuals** — waitlist, blog, header/footer structure, theme toggle survive; design system, hero, and sections are rebuilt.
3. **Dark default, toggle kept** — Solus Dark is the default; Solus Light available via the existing toggle (stored preference wins).

## Design language (ported from `apps/desktop`)

- **Tokens** verbatim from `theme/tokens.constants.ts`: Solus Dark (`--bg #0A0C0F`, `--sur`, `--sur2`, `--bd`, `--tx`, `--mut`, status colors) and Solus Light, plus domain colors `--sw/--ee/--me/--rt` and amber accent `--acc #E5A43B` / `--acc-ink`. Light theme accent darkened to `#A87514` for contrast on white.
- **Fonts:** IBM Plex Sans (UI) + IBM Plex Mono (labels/code), replacing Inter.
- **Idioms:** 3px radii on controls, 1px `--bd` borders on layered surfaces, mono uppercase micro-labels with 0.12em tracking, SOL orb radial gradient + pulse.

## Page structure (starter)

1. **Hero** — mono kicker, headline on the product thesis ("Your robot lives in four worlds. Solus makes them one."), sub-copy naming GitHub/KiCad/Onshape/ROS and the graph, waitlist CTA (amber primary) + walkthrough link.
2. **Product mockup window** — styled like the desktop app: title bar, sidebar (projects + four domain chips in domain colors), 2×2 domain panels (Software/Electrical/Mechanical/Runtime with plausible files/signals), and a **SOL diagnosis strip** (orb + a caught I2C conflict warning + a fingerprint match line) replacing the old terminal.
3. **How it works** — three steps: Connect your tools → One living graph → Catch breaks early.
4. **CTA band** + footer.

## Files touched

`app/layout.js` (fonts, metadata, dark-default theme init), `app/globals.css` (full token/style rewrite; blog + modal + toast surfaces re-implemented on the new tokens), `app/page.js` (new starter structure), `components/site-header.jsx` (SOLUS wordmark + orb, nav), `components/site-footer.jsx`, `components/hero-actions.jsx`, `components/waitlist-trigger.jsx` (copy rebrand, simplified CTA markup), `components/page-animations.jsx` (selector rename only), plus `Solus Forge → Solus` copy in blog metadata and the waitlist API response. `theme-toggle.jsx` and blog page structure are untouched.

## Verification

`next build` green; visual pass in dark and light themes (hero, mockup, how-it-works, CTA, footer) via served production build. `apps/web` has no test infrastructure; this is a content/style change — flagged in the completion report rather than bootstrapping a test stack unasked.
