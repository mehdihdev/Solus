// Auth session store. Bridges Supabase Auth (ADR-009) into app state, with a
// dev bypass when Supabase env is absent so the onboarding prototype stays
// demoable. The `onboarded` flag is persisted locally for this slice; the real
// app will derive it from the user's team/project state via the API.
import { create, type StateCreator } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User as SupabaseUser } from '@supabase/supabase-js'
import { supabase, supabaseConfigured } from '../lib/supabase'
import { getDesktopOAuthBridge } from '../lib/desktopBridge'
import { runGithubOAuth } from '../features/auth/githubOAuth'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthUser {
  email: string
  /** Whether Supabase has confirmed the email. Undefined ⇒ treat as verified
   * (dev bypass / OAuth); only an explicit `false` drives the verify gate
   * (SOLUSDEV-82), mirroring the backend's "absent claim ⇒ verified". */
  emailVerified?: boolean
}

export interface AuthResult {
  error?: string
  /** True when signup succeeded but the email must be confirmed before a session exists. */
  needsConfirmation?: boolean
}

/** Derive our AuthUser from a Supabase session user, reading verification state. */
export function toAuthUser(user: SupabaseUser | null | undefined): AuthUser | null {
  if (!user?.email) return null
  const verified = Boolean(user.email_confirmed_at) || Boolean(user.user_metadata?.email_verified)
  return { email: user.email, emailVerified: verified }
}

export interface AuthState {
  status: AuthStatus
  user: AuthUser | null
  accessToken: string | null
  onboarded: boolean
  bootstrap: () => Promise<void>
  signUpWithPassword: (email: string, password: string) => Promise<AuthResult>
  signInWithPassword: (email: string, password: string) => Promise<AuthResult>
  signInWithGitHub: () => Promise<AuthResult>
  sendMagicLink: (email: string) => Promise<AuthResult>
  /** Re-send the signup confirmation email. */
  resendConfirmation: (email: string) => Promise<AuthResult>
  /** Start password recovery: Supabase emails a recovery code (SOLUSDEV-82). */
  requestPasswordReset: (email: string) => Promise<AuthResult>
  /** Finish recovery: verify the emailed code, then set the new password. */
  confirmPasswordReset: (email: string, code: string, newPassword: string) => Promise<AuthResult>
  signOut: () => Promise<void>
  completeOnboarding: () => void
  setSession: (user: AuthUser | null, accessToken: string | null) => void
  /** Detach the Supabase auth listener (call from the App effect cleanup). */
  teardown: () => void
}

/** Holds the Supabase auth subscription so it can be detached on teardown. */
let authSubscription: { unsubscribe: () => void } | null = null

export const AUTH_STORAGE_KEY = 'solus_auth_v1'

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message: unknown }).message)
  }
  return 'Something went wrong. Please try again.'
}

type AuthCreator = StateCreator<AuthState, [['zustand/persist', unknown]], []>
type AuthSet = Parameters<AuthCreator>[0]
type AuthGet = Parameters<AuthCreator>[1]

/** Session lifecycle: bootstrap, the Supabase listener, sign-out, onboarding flag. */
function sessionActions(
  set: AuthSet,
  get: AuthGet
): Pick<AuthState, 'setSession' | 'bootstrap' | 'teardown' | 'signOut' | 'completeOnboarding'> {
  return {
    setSession: (user, accessToken) =>
      set({ user, accessToken, status: user ? 'authenticated' : 'unauthenticated' }),

    bootstrap: async () => {
      if (!supabase) {
        // Dev bypass: trust any locally-persisted session.
        set((s) => ({ status: s.user ? 'authenticated' : 'unauthenticated' }))
        return
      }
      try {
        const { data } = await supabase.auth.getSession()
        const session = data.session
        set({
          user: toAuthUser(session?.user),
          accessToken: session?.access_token ?? null,
          status: session ? 'authenticated' : 'unauthenticated'
        })
        // Replace any prior listener so bootstrap is idempotent (StrictMode/HMR).
        authSubscription?.unsubscribe()
        const { data: listener } = supabase.auth.onAuthStateChange((_event, s) => {
          get().setSession(toAuthUser(s?.user), s?.access_token ?? null)
        })
        authSubscription = listener.subscription
      } catch {
        // Never hang at the splash screen if session lookup fails.
        set({ user: null, accessToken: null, status: 'unauthenticated' })
      }
    },

    teardown: () => {
      authSubscription?.unsubscribe()
      authSubscription = null
    },

    signOut: async () => {
      if (supabase) await supabase.auth.signOut()
      set({ user: null, accessToken: null, status: 'unauthenticated', onboarded: false })
    },

    completeOnboarding: () => set({ onboarded: true })
  }
}

/** Credential entry points: password, GitHub OAuth, magic link, confirmation resend. */
function credentialActions(
  set: AuthSet,
  get: AuthGet
): Pick<
  AuthState,
  | 'signUpWithPassword'
  | 'signInWithPassword'
  | 'resendConfirmation'
  | 'signInWithGitHub'
  | 'sendMagicLink'
  | 'requestPasswordReset'
  | 'confirmPasswordReset'
> {
  void set
  return {
    signUpWithPassword: async (email, password) => {
      if (!supabase) {
        get().setSession({ email }, 'dev-bypass-token')
        return {}
      }
      const { data, error } = await supabase.auth.signUp({ email, password })
      if (error) return { error: errorMessage(error) }
      // With email confirmation on, Supabase returns no session until the user
      // clicks the link. The confirm screen then polls signInWithPassword.
      if (data.session) {
        get().setSession(toAuthUser(data.user) ?? { email }, data.session.access_token)
        return {}
      }
      return { needsConfirmation: true }
    },

    signInWithPassword: async (email, password) => {
      if (!supabase) {
        get().setSession({ email }, 'dev-bypass-token')
        return {}
      }
      const { data, error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) return { error: errorMessage(error) }
      if (data.session) {
        get().setSession(toAuthUser(data.user) ?? { email }, data.session.access_token)
      }
      return {}
    },

    resendConfirmation: async (email) => {
      if (!supabase) return {}
      const { error } = await supabase.auth.resend({ type: 'signup', email })
      return error ? { error: errorMessage(error) } : {}
    },

    requestPasswordReset: async (email) => {
      // Dev bypass: no Supabase project — report success so the UI flow is demoable.
      if (!supabase) return {}
      const { error } = await supabase.auth.resetPasswordForEmail(email)
      return error ? { error: errorMessage(error) } : {}
    },

    confirmPasswordReset: async (email, code, newPassword) => {
      if (!supabase) return {}
      // The emailed recovery code establishes a short-lived session, which
      // authorizes the password update (SOLUSDEV-82 — in-app, no browser redirect).
      const { error: verifyError } = await supabase.auth.verifyOtp({
        email,
        token: code,
        type: 'recovery'
      })
      if (verifyError) return { error: errorMessage(verifyError) }
      const { error: updateError } = await supabase.auth.updateUser({ password: newPassword })
      return updateError ? { error: errorMessage(updateError) } : {}
    },

    signInWithGitHub: async () => {
      if (!supabase) {
        get().setSession({ email: 'dev@solus.local' }, 'dev-bypass-token')
        return {}
      }
      const bridge = getDesktopOAuthBridge()
      if (!bridge) {
        return { error: 'GitHub sign-in is only available in the Solus desktop app.' }
      }
      // Loopback OAuth: main opens the browser and captures the redirect; the
      // session lands via onAuthStateChange after the code exchange.
      return runGithubOAuth(supabase, bridge)
    },

    sendMagicLink: async (email) => {
      if (!supabase) {
        get().setSession({ email }, 'dev-bypass-token')
        return {}
      }
      const { error } = await supabase.auth.signInWithOtp({ email })
      return error ? { error: errorMessage(error) } : {}
    }
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      status: 'loading',
      user: null,
      accessToken: null,
      onboarded: false,
      ...sessionActions(set, get),
      ...credentialActions(set, get)
    }),
    {
      name: AUTH_STORAGE_KEY,
      // Only persist what the dev bypass needs; Supabase owns real session storage.
      partialize: (s) => ({ user: s.user, onboarded: s.onboarded })
    }
  )
)

export { supabaseConfigured }
