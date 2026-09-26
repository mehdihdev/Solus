// Render showcase.html with Playwright.
//
//   node tools/render.mjs beats          one still per beat → render/beats/*.png + contact sheet
//   node tools/render.mjs frames [n]     4 subframes per 60 fps frame → render/sub/*.jpg (n pages in parallel)
//   node tools/render.mjs cues           write audio/cues.json from the page's CUES
//
// playwright-core is not a repo dependency; point PW_CORE at an install (default: ./node_modules).
// CHROMIUM may override the browser binary (default: Playwright's cached headless shell).
import { mkdirSync, writeFileSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "render");
const PAGE = pathToFileURL(join(ROOT, "showcase.html")).href;
const SUBFRAMES = 4;

const pwDir =
  process.env.PW_CORE ?? join(ROOT, "node_modules", "playwright-core");
const { chromium } = await import(pathToFileURL(join(pwDir, "index.mjs")).href);

function defaultChromium() {
  const cache = join(homedir(), "Library", "Caches", "ms-playwright");
  const dir = readdirSync(cache)
    .filter((d) => d.startsWith("chromium_headless_shell-"))
    .sort()
    .pop();
  return dir
    ? join(
        cache,
        dir,
        "chrome-headless-shell-mac-arm64",
        "chrome-headless-shell",
      )
    : undefined;
}

async function openPages(browser, count, query = "") {
  return Promise.all(
    Array.from({ length: count }, async () => {
      const page = await browser.newPage({
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 1,
      });
      await page.goto(`${PAGE}${query}`);
      await page.waitForFunction(() => window.READY === true);
      return page;
    }),
  );
}

async function shot(page, t, path, type) {
  await page.evaluate((time) => window.seek(time), t);
  const clip = { x: 0, y: 0, width: 1920, height: 1080 };
  await page.screenshot(
    type === "jpeg" ? { path, clip, type, quality: 94 } : { path, clip, type },
  );
}

async function beats(browser) {
  const dir = join(OUT, "beats");
  mkdirSync(dir, { recursive: true });
  const [page] = await openPages(browser, 1, "?debug");
  const { P, T } = await page.evaluate(() => window.SHOWCASE);
  const beatCount = Math.round(T / P);
  // Mid-beat: the moment a viewer reads the state that landed on the beat.
  for (let i = 0; i < beatCount; i++) {
    const name = `b${String(i + 1).padStart(2, "0")}_bar${Math.floor(i / 4) + 1}.${(i % 4) + 1}.png`;
    await shot(page, i * P + P * 0.55, join(dir, name), "png");
  }
  execFileSync("ffmpeg", [
    "-loglevel",
    "error",
    "-y",
    "-pattern_type",
    "glob",
    "-i",
    join(dir, "b*.png"),
    "-vf",
    `scale=480:-1,tile=8x${Math.ceil(beatCount / 8)}:padding=6:color=0x222222`,
    "-frames:v",
    "1",
    join(OUT, "beats-sheet.png"),
  ]);
  console.log(`beats → ${dir} + render/beats-sheet.png`);
}

async function frames(browser, workers) {
  const dir = join(OUT, "sub");
  mkdirSync(dir, { recursive: true });
  const pages = await openPages(browser, workers);
  const { FRAMES, FPS } = await pages[0].evaluate(() => window.SHOWCASE);
  const total = FRAMES * SUBFRAMES;
  let next = 0;
  const started = Date.now();
  await Promise.all(
    pages.map(async (page) => {
      for (let i = next++; i < total; i = next++) {
        // Subframes are centred on the frame time (shutter spans ±3/8 of a frame).
        const t =
          (Math.floor(i / SUBFRAMES) +
            ((i % SUBFRAMES) - (SUBFRAMES - 1) / 2) / SUBFRAMES) /
          FPS;
        await shot(
          page,
          t,
          join(dir, `${String(i).padStart(6, "0")}.jpg`),
          "jpeg",
        );
        if (i % 400 === 0)
          console.log(
            `${i}/${total}  ${((Date.now() - started) / 1000).toFixed(0)}s`,
          );
      }
    }),
  );
  console.log(`subframes → ${dir}`);
}

async function cues(browser) {
  const [page] = await openPages(browser, 1);
  const data = await page.evaluate(() => ({
    T: window.SHOWCASE.T,
    cues: window.SHOWCASE.CUES,
    musicFade: window.SHOWCASE.MUSIC_FADE,
  }));
  writeFileSync(
    join(ROOT, "audio", "cues.json"),
    `${JSON.stringify(data, null, 1)}\n`,
  );
  console.log(`${data.cues.length} cues → audio/cues.json`);
}

const [mode = "beats", arg] = process.argv.slice(2);
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM ?? defaultChromium(),
});
try {
  if (mode === "beats") await beats(browser);
  else if (mode === "frames") await frames(browser, Number(arg ?? 6));
  else if (mode === "cues") await cues(browser);
  else throw new Error(`unknown mode ${mode}`);
} finally {
  await browser.close();
}
