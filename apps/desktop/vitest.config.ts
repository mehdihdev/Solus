import { resolve } from 'path'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * Vitest config for the renderer. electron-vite owns the app build; tests run
 * against the renderer sources directly under jsdom.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@renderer': resolve(__dirname, 'src/renderer/src')
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    // The ARM CI runner is a ~2 GB box (see typecheck:node in .gitlab-ci.yml).
    // Vitest's default of one jsdom worker per core exhausted it and test:node
    // died with a worker crash rather than an assertion (pipeline #2821709829);
    // the same crash reproduces locally under memory pressure. Two workers
    // bound the footprint; local runs keep the default.
    ...(process.env.CI ? { maxWorkers: 2 } : {}),
    setupFiles: ['./test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: true,
    // Hermetic auth: ignore any local .env so tests run the dev-bypass path
    // (supabase === null) and never touch a real Supabase project or the network.
    // The Supabase pair must stay '' — blank is what `isConfigured` keys the
    // bypass on (lib/supabase.ts).
    //
    // The API base is UNREACHABLE rather than blank. Blank used to double as the
    // hermeticity guard, but it also made '' a legitimate production value, which
    // is how the renderer shipped relative URLs that missed the API entirely —
    // and once client.ts started treating blank as unset, '' resolved to
    // localhost:8000, i.e. a developer's REAL running API.
    //
    // Port 9 on loopback (discard) refuses instantly: no DNS, no listener. That
    // matters as much as unreachability — an unresolvable HOSTNAME fails only
    // after a DNS timeout, which lands after jsdom has torn `window` down, and
    // any component that setStates in its catch block then throws
    // "window is not defined" as an unhandled rejection. Connection-refused is
    // synchronous enough to land inside the test that caused it.
    env: {
      VITE_SUPABASE_URL: '',
      VITE_SUPABASE_ANON_KEY: '',
      VITE_API_BASE_URL: 'http://127.0.0.1:9/api/v1'
    }
  }
})
