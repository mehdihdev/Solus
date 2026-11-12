// Credit display constants shared by Billing › Credits and SOL's usage panel
// (SOLUSDEV-325).

/** At or below this balance SOL shows its top-up card and Billing turns the
 *  balance warn (provisional). */
export const LOW_BALANCE_CREDITS = 100

export function formatCredits(n: number): string {
  return n.toLocaleString('en-US')
}
