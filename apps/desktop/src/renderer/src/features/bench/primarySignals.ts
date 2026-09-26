/** Presentation roles come from channel evidence, never signal names or units. */
export function partitionSignals<
  T extends { series: { signal: string; display_role?: string | null } }
>(rows: readonly T[]): { primary: T[]; diagnostics: T[] } {
  const primary: T[] = []
  const diagnostics: T[] = []
  for (const row of rows) {
    if (row.series.display_role === 'diagnostic') diagnostics.push(row)
    else primary.push(row)
  }
  return { primary, diagnostics }
}
