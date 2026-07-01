import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import type { PluginOption } from 'vite'

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
    plugins: [react(), tailwindcss(), devCsp()]
  }
})
