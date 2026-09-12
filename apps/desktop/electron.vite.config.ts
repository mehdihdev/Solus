import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { loadEnv, type PluginOption } from 'vite'
import { assertProdAuthEnv } from './src/renderer/src/lib/prodAuthGuard'
import { apiOriginForCsp, widenConnectSrc } from './src/renderer/src/lib/cspConnect'

// Dev only: Vite's React-Refresh preamble is an inline <script>, which the strict
// production CSP (script-src 'self') blocks in Electron → blank window. Relax
// script-src for the dev server only; the built index.html keeps the strict policy.
function devCsp(): PluginOption {
  return {
    name: 'dev-csp',
    apply: 'serve',
    transformIndexHtml: (html: string): string =>
      html.replace("script-src 'self'", "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
  }
}

// SOLUSDEV-152 WS-D (CLAUDE.md §7): a production renderer build without Supabase
// env would ship the dev fake-login bypass — fail the build instead. The check
// reads Vite's RESOLVED config: `config.env` is exactly what `import.meta.env`
// receives at runtime (.env files via loadEnv + matching process.env vars), and
// `config.mode` is Vite's resolved mode. The gate keys on mode, not
// `config.isProduction`, because electron-vite forces NODE_ENV=production for
// every `build` command — which also means `import.meta.env.DEV` is false in
// ALL built bundles, so the bypass is dead-code-eliminated from every build and
// a --mode development build without env boots to authStore's explicit config
// error, never fake auth. `apply: 'build'` keeps the dev server (where the
// bypass legitimately lives) untouched.
function prodAuthGuard(): PluginOption {
  return {
    name: 'solus-prod-auth-guard',
    apply: 'build',
    configResolved(config) {
      assertProdAuthEnv(config.env, config.mode)
    }
  }
}

// SOLUSDEV-152: the renderer's CSP must list the Solus REST API origin under
// connect-src or the browser refuses every fetch to the API before it is sent
// (surfacing as the misleading "Solus can't reach its API" state). The origin is
// derived from VITE_API_BASE_URL — captured from Vite's resolved env — so dev
// (http loopback) and packaged builds (https API) are each scoped exactly. Runs
// on both serve and build (no `apply`), unlike devCsp which is dev-only.
function apiCsp(): PluginOption {
  let apiOrigin: string | null = null
  return {
    name: 'solus-api-csp',
    configResolved(config) {
      apiOrigin = apiOriginForCsp(config.env.VITE_API_BASE_URL as string | undefined)
    },
    transformIndexHtml: (html: string): string => widenConnectSrc(html, apiOrigin)
  }
}

// SOLUSDEV-68 live verification: main and preload import `@solus/shared-types`
// (the CTR-06 orb↔overlay contract, since SOL-IPC-01). electron-vite externalizes
// `dependencies` by default, so the built bundles emitted
// `require("@solus/shared-types")` — but that package ships RAW TypeScript
// (`main: "src/index.ts"`), which Node cannot execute: the app died on launch
// with ERR_MODULE_NOT_FOUND. vitest and tsc both transpile TS, so every test and
// the typecheck passed while the app could not start. Bundle it instead.
const bundleWorkspaceContracts = externalizeDepsPlugin({ exclude: ['@solus/shared-types'] })

// The repo root holds the ONE `.env` (see packages/api/.../config.py). electron-vite
// defaults envDir to each build's root — `apps/desktop` — so the renderer read a second,
// hand-maintained env file that could (and did) shadow the real one with a blank
// `VITE_API_BASE_URL`. Pointing every build at the root removes the shadow entirely.
//
// Safe with a root file full of secrets: Vite only inlines vars matching envPrefix, which
// stays at its default (`VITE_`/`RENDERER_VITE_` for the renderer, `MAIN_VITE_` for main).
// The ~70 unprefixed keys — Stripe, AWS, OAuth secrets — are read and discarded, never
// reaching a bundle. Do NOT widen envPrefix to '' here; that would ship them to the client.
const ENV_DIR = resolve(__dirname, '../..')

// Renderer dev-server port. Several worktrees run this app on one machine at once
// (docs/WORKTREES.md), and Vite's silent fallback to the next free port would hand
// the API a CORS origin nobody configured. Override with VITE_DEV_PORT (shell or
// root .env); strictPort makes a busy port a loud failure instead.
const DEV_PORT =
  Number(process.env.VITE_DEV_PORT ?? loadEnv('development', ENV_DIR, 'VITE_').VITE_DEV_PORT) ||
  5173

export default defineConfig({
  main: { envDir: ENV_DIR, plugins: [bundleWorkspaceContracts] },
  preload: { envDir: ENV_DIR, plugins: [bundleWorkspaceContracts] },
  renderer: {
    envDir: ENV_DIR,
    resolve: {
      // The monorepo has more than one react/react-dom copy (root node_modules vs this
      // app's). Force a single instance, else zustand binds a different React than react-dom
      // → "Invalid hook call" and a blank window on first render.
      dedupe: ['react', 'react-dom'],
      alias: {
        '@renderer': resolve('src/renderer/src')
      }
    },
    // pnpm hoists deps (e.g. @fontsource) to the monorepo-root node_modules, which sits above
    // the renderer root — let the dev server serve from there (cwd is apps/desktop → repo root).
    server: {
      port: DEV_PORT,
      strictPort: true,
      fs: {
        allow: [resolve('../..')]
      }
    },
    plugins: [react(), tailwindcss(), devCsp(), apiCsp(), prodAuthGuard()]
  }
})
