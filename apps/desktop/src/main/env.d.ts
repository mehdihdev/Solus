/// <reference types="electron-vite/node" />

// The main build gets Vite env too: electron-vite applies envPrefix
// `MAIN_VITE_`/`VITE_` to it, and electron.vite.config.ts points envDir at the
// repo root, so main and the renderer resolve the same keys from the one root
// `.env`. electron-vite's bundled `ImportMetaEnv` knows nothing about ours, and
// this interface merges into it (declaration merging — this file must stay a
// global script, so never add a top-level import/export here).
//
// Only what main actually reads: `companion.ts` needs the API base to tell the
// companion which origin to dial back to.
interface ImportMetaEnv {
  /** Solus REST API base URL. Blank/absent falls back to the loopback default
   *  via `resolveApiBaseUrl` — never treat '' as a usable base. */
  readonly VITE_API_BASE_URL?: string
}
