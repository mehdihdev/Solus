import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import type { PluginOption } from 'vite'
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

export default defineConfig({
  main: {},
  preload: {},
  renderer: {
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
      fs: {
        allow: [resolve('../..')]
      }
    },
    plugins: [react(), tailwindcss(), devCsp(), apiCsp(), prodAuthGuard()]
  }
})
