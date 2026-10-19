// Home's row stagger (SOLUSDEV-317): each row of a list enters a little after
// the one above it, capped so a long list never makes the last row wait.
// The keyframes and the reduced-motion switch live in home.css.
import './home.css'

/** Delay between consecutive rows. */
export const HOME_STAGGER_MS = 30
/** Rows past this index share the last delay. */
export const HOME_STAGGER_CAP = 8

export function homeStagger(index: number): React.CSSProperties {
  return { animationDelay: `${Math.min(index, HOME_STAGGER_CAP) * HOME_STAGGER_MS}ms` }
}
