# Solus brand assets

Source SVGs for the Solus mark — the "ball of energy" orb and the SOLUS wordmark — extracted from the app's design system as a starting point for a finished logo.

## Files

| File                            | What it is                                         | Use for                                        |
| ------------------------------- | -------------------------------------------------- | ---------------------------------------------- |
| `orb.svg`                       | The orb with its soft glow, on transparent         | Hero mark, the standalone "energy ball"        |
| `orb-flat.svg`                  | The orb, no glow, filled edge-to-edge              | Favicon, very small sizes, monochrome contexts |
| `wordmark-on-dark.svg`          | Orb + SOLUS, **light** text, transparent bg        | Dark UIs, dark headers                         |
| `wordmark-on-light.svg`         | Orb + SOLUS, **dark** text, transparent bg         | Light/print backgrounds                        |
| `lockup-stacked.svg`            | Orb above SOLUS, vertical                          | Square/centered placements, splash             |
| `app-icon.svg`                  | Orb on the brand dark background, rounded square   | App / dock / store icon (export to PNG sizes)  |
| `orb-spectrum.svg`              | **Iridescent multicolor** orb (four domains fused) | Expressive / hero mark, marketing              |
| `wordmark-spectrum-on-dark.svg` | Spectrum orb + SOLUS, light text                   | Dark marketing surfaces                        |
| `app-icon-spectrum.svg`         | Spectrum orb on the dark rounded square            | Colorful app / store icon                      |

## Spectrum variant

The `*-spectrum` files blend the product's four domain colors — software `#62A9FF`, electrical `#E5A43B`, mechanical `#E87FAE`, runtime `#5BCD8C` (plus violet/teal accents) — into one iridescent orb. It's a soft spectral blend, not a literal rainbow, and it carries the "one graph across four worlds" idea in the mark itself.

Built with overlapping blurred color fields composited in `mix-blend-mode: screen` over a near-black ball, plus the same upper-left highlight and glow as the amber orb. **Caveat:** `mix-blend-mode` renders correctly in browsers and recent Figma/Illustrator, but some tools flatten or drop it on import — if a multicolor file looks wrong there, rasterize it to PNG (it exports correctly from any browser) or rebuild the blend natively.

## Colors

| Token            | Hex                   | Role                     |
| ---------------- | --------------------- | ------------------------ |
| Accent (amber)   | `#E5A43B`             | The orb + accent text    |
| Accent highlight | `#FBE3A6` → `#EFBB58` | Orb inner gradient stops |
| Ink              | `#0A0C0F`             | Brand dark background    |
| Text (on dark)   | `#E6E9EE`             | Wordmark on dark         |
| Text (on light)  | `#1A1E26`             | Wordmark on light        |

The product ships three other accents (teal `#50D0B4`, blue `#62A9FF`, violet `#B98BEA`) as a user setting; **amber is the brand default**. Any of them can recolor the orb by swapping the gradient/glow fill.

## Construction

- **Orb** = a circle filled with a radial gradient whose highlight sits at ~35% / 32% (upper-left), fading to transparent, plus a blurred copy behind it for the glow. This mirrors the live CSS: `radial-gradient(circle at 35% 32%, accent, transparent)` + a soft `box-shadow`.
- **Wordmark** = orb + `SOLUS` set in **IBM Plex Sans, weight 700, letter-spacing ~0.12em**, orb diameter ≈ cap height, gap ≈ 0.25× the text size.

## Font note

The wordmark SVGs reference the live font (`IBM Plex Sans`). They render correctly anywhere that font is installed (it's bundled in the app via `@fontsource`). **Before handing the wordmark to an external tool or print**, convert the text to outlines/paths so it doesn't depend on the font being present. The orb files have no text and are safe as-is.

IBM Plex Sans is open source (SIL OFL): https://github.com/IBM/plex
