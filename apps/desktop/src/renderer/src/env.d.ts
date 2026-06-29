/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Supabase project URL, e.g. https://xxxx.supabase.co. Optional; absent enables dev bypass. */
  readonly VITE_SUPABASE_URL?: string
  /** Supabase anonymous (publishable) key. Optional; absent enables dev bypass. */
  readonly VITE_SUPABASE_ANON_KEY?: string
  /** Solus REST API base URL. Defaults to http://localhost:8000 in dev. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
