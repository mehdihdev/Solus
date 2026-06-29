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
    setupFiles: ['./test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: true,
    // Hermetic auth: ignore any local .env so tests run the dev-bypass path
    // (supabase === null) and never touch a real Supabase project or the network.
    env: {
      VITE_SUPABASE_URL: '',
      VITE_SUPABASE_ANON_KEY: '',
      VITE_API_BASE_URL: ''
    }
  }
})
