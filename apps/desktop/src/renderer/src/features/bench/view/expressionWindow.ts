// SOLUSDEV-319 Phase 4 H-1: amortised O(1) storage for the windowed filters (ma, integ).
// Twin of _WindowSum in packages/api/src/solus_api/livebench/view/expression.py.

/** Array-backed FIFO: O(1) push, amortised O(1) shift (compacts once half is dead). */
export class Fifo<T> implements Iterable<T> {
  private items: T[] = []
  private head = 0

  get length(): number {
    return this.items.length - this.head
  }

  push(item: T): void {
    this.items.push(item)
  }

  shift(): T | undefined {
    if (this.head >= this.items.length) return undefined
    const item = this.items[this.head++]
    if (this.head * 2 >= this.items.length) {
      this.items = this.items.slice(this.head)
      this.head = 0
    }
    return item
  }

  first(): T | undefined {
    return this.items[this.head]
  }

  last(): T | undefined {
    return this.length > 0 ? this.items[this.items.length - 1] : undefined
  }

  clear(): void {
    this.items = []
    this.head = 0
  }

  *[Symbol.iterator](): Iterator<T> {
    for (let i = this.head; i < this.items.length; i++) yield this.items[i]
  }
}

/**
 * Running sum of a FIFO of terms with amortised O(1) push/pop.
 *
 * Neumaier-compensated so a term leaving the window does not take smaller terms'
 * precision with it, and recomputed oldest->newest once as many terms have left as
 * remain, so drift never accumulates past one window. A non-finite partial sum makes
 * the result NaN until no term that could overflow is left, when the oldest->newest
 * recomputation decides again.
 */
export class WindowSum {
  readonly terms = new Fifo<number>()
  private sum = 0
  private comp = 0
  private unsafe = 0
  private removed = 0
  private overflow = false
  /** Below this magnitude, maxTerms terms cannot overflow a double. */
  private readonly safeTerm: number

  constructor(maxTerms: number) {
    this.safeTerm = Number.MAX_VALUE / maxTerms
  }

  push(term: number): void {
    this.terms.push(term)
    if (!(Math.abs(term) < this.safeTerm)) this.unsafe++
    this.add(term)
  }

  pop(): void {
    const term = this.terms.shift()
    if (term === undefined) return
    this.removed++
    if (!(Math.abs(term) < this.safeTerm)) this.unsafe--
    if (this.removed >= this.terms.length || (this.overflow && this.unsafe === 0)) {
      this.recompute()
    } else {
      this.add(-term)
    }
  }

  clear(): void {
    this.terms.clear()
    this.unsafe = 0
    this.recompute()
  }

  value(): number {
    return this.overflow ? Number.NaN : this.sum + this.comp
  }

  private add(term: number): void {
    if (this.overflow) return
    const total = this.sum + term
    if (!Number.isFinite(total)) {
      this.overflow = true
      return
    }
    this.comp +=
      Math.abs(this.sum) >= Math.abs(term) ? this.sum - total + term : term - total + this.sum
    this.sum = total
  }

  private recompute(): void {
    this.sum = 0
    this.comp = 0
    this.removed = 0
    this.overflow = false
    for (const term of this.terms) this.add(term)
  }
}

interface Sample {
  readonly t: number
  readonly value: number
}

/** Finite samples in (t - w, t], newest maxSamples, reduced through a running WindowSum. */
abstract class WindowedFilter {
  protected readonly samples = new Fifo<Sample>()
  protected readonly sum: WindowSum
  private lastT: number | null = null

  constructor(
    private readonly window: number,
    private readonly maxSamples: number
  ) {
    this.sum = new WindowSum(maxSamples)
  }

  update(t: number, x: number): number {
    if (this.lastT !== null && t - this.lastT > this.window) {
      this.samples.clear()
      this.sum.clear()
    }
    this.lastT = t
    if (Number.isFinite(x)) this.push(t, x)
    while (this.isStale(t - this.window)) {
      this.samples.shift()
      this.evicted()
    }
    const result = this.reduce()
    return Number.isFinite(result) ? result : Number.NaN
  }

  size(): number {
    return this.samples.length
  }

  private isStale(cutoff: number): boolean {
    const oldest = this.samples.first()
    return oldest !== undefined && (oldest.t <= cutoff || this.samples.length > this.maxSamples)
  }

  protected abstract push(t: number, x: number): void
  protected abstract evicted(): void
  protected abstract reduce(): number
}

/** Term per sample: the sample's value. */
export class MovingAverage extends WindowedFilter {
  protected push(t: number, x: number): void {
    this.samples.push({ t, value: x })
    this.sum.push(x)
  }

  protected evicted(): void {
    this.sum.pop()
  }

  protected reduce(): number {
    return this.samples.length > 0 ? this.sum.value() / this.samples.length : Number.NaN
  }
}

/** Term per consecutive sample pair: the trapezoid between them. */
export class Integral extends WindowedFilter {
  protected push(t: number, x: number): void {
    const prev = this.samples.last()
    if (prev) this.sum.push(((t - prev.t) * (x + prev.value)) / 2)
    this.samples.push({ t, value: x })
  }

  protected evicted(): void {
    this.sum.pop()
  }

  protected reduce(): number {
    return this.sum.value()
  }
}
