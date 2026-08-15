import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// The repo root holds the ONE `.env` (see packages/api/.../config.py). Next loads env
// from its own project root — `apps/web` — so this app used to need a second copy of the
// Google credentials, which then drifted out of the root file. Load the root file here
// instead: next.config runs before the server boots, so `process.env` is populated by the
// time the waitlist route handler reads it.
//
// `process.loadEnvFile` is built into Node (package.json pins engines.node >= 22), so this
// costs no dependency. Real environment variables already set win — it does not overwrite
// them — which keeps CI and any hosting platform's injected config authoritative.
const ROOT_ENV = resolve(dirname(fileURLToPath(import.meta.url)), '../..', '.env')
if (existsSync(ROOT_ENV)) {
  process.loadEnvFile(ROOT_ENV)
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true
}

export default nextConfig
