// "Ask SOL to set it up" (SOLUSDEV-250 / I3). The SOL feature has no
// composer-prefill seam (OrbChat's input is local state; solusActions SENDS a
// turn rather than drafting one), so the hand-off copies the request to the
// clipboard, says so with the shell toast, and opens the SOL screen. Pure over
// its injected deps; the defaults wrap the browser clipboard and shell store.
import { SOL_SETUP_MESSAGE } from '../project/codeEnvironment.constants'
import { useShellStore, type MainScreen, type ShellToast } from './shellStore'

export interface SolHandoffDeps {
  /** The shell's screen navigator; absent when the row has no way to navigate. */
  navigate?: (screen: MainScreen) => void
  writeText?: (text: string) => Promise<void>
  toast?: (toast: ShellToast) => void
}

const COPIED: ShellToast = {
  kind: 'ok',
  title: 'Request copied for SOL',
  body: 'Paste it into the SOL composer and send — SOL will ask before it runs anything.',
  action: 'Open SOL',
  screen: 'sol'
}

function copyFailed(): ShellToast {
  return {
    kind: 'warn',
    title: "Couldn't copy the request",
    body: `Type this into SOL: “${SOL_SETUP_MESSAGE}”`,
    action: 'Open SOL',
    screen: 'sol'
  }
}

function defaultWriteText(text: string): Promise<void> {
  return navigator.clipboard.writeText(text)
}

export async function handOffToSol({
  navigate,
  writeText = defaultWriteText,
  toast = (next) => useShellStore.getState().setToast(next)
}: SolHandoffDeps): Promise<void> {
  const copied = await writeText(SOL_SETUP_MESSAGE).then(
    () => true,
    () => false
  )
  toast(copied ? COPIED : copyFailed())
  navigate?.('sol')
}
