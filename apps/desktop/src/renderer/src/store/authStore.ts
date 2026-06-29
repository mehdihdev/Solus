// Auth session store. Bridges Supabase Auth (ADR-009) into app state, with a
// dev bypass when Supabase env is absent so the onboarding prototype stays
// demoable. The `onboarded` flag is persisted locally for this slice; the real
// app will derive it from the user's team/project state via the API.
import { create, type StateCreator } from 'zustand'
import { persist } from 'zustand/middleware'
import { supabase, supabaseConfigured } from '../lib/supabase'
import { getDesktopOAuthBridge } from '../lib/desktopBridge'
import { runGithubOAuth } from '../features/auth/githubOAuth'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthUser {
  email: string
}

export interface AuthResult {
  error?: string
  /** True when signup succeeded but the email must be confirmed before a session exists. */
  needsConfirmation?: boolean
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
          user: session?.user?.email ? { email: session.user.email } : null,
          accessToken: session?.access_token ?? null,
          status: session ? 'authenticated' : 'unauthenticated'
        })
        // Replace any prior listener so bootstrap is idempotent (StrictMode/HMR).
        authSubscription?.unsubscribe()
        const { data: listener } = supabase.auth.onAuthStateChange((_event, s) => {
          get().setSession(s?.user?.email ? { email: s.user.email } : null, s?.access_token ?? null)
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
        get().setSession({ email }, data.session.access_token)
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
        get().setSession(
          data.user?.email ? { email: data.user.email } : { email },
          data.session.access_token
        )
      }
      return {}
    },

    resendConfirmation: async (email) => {
      if (!supabase) return {}
      const { error } = await supabase.auth.resend({ type: 'signup', email })
      return error ? { error: errorMessage(error) } : {}
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
