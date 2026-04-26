/**
 * formatters.ts
 *
 * Pure display formatting utilities for paise-to-rupees conversion and dates.
 *
 * Key design decisions:
 *   - Paise-to-rupees conversion uses integer arithmetic (floor division + modulo),
 *     never float division, to avoid IEEE 754 rounding artifacts. (P9)
 *   - The ₹ symbol is included in formatRupees so all call sites are consistent.
 */

/**
 * Convert paise to a formatted rupee string using integer arithmetic only.
 *
 * Uses floor division and modulo to avoid floating-point rounding. (P9)
 * The en-IN locale formats the whole part with Indian grouping (e.g. 1,00,000).
 */
export function formatRupees(paise: number): string {
  const whole = Math.trunc(paise / 100)
  const fractional = Math.abs(paise % 100).toString().padStart(2, '0')
  return `₹${whole.toLocaleString('en-IN')}.${fractional}`
}

/**
 * Format an ISO timestamp for the Indian locale with medium date and short time.
 * Returns a dash for missing values so table cells never render empty.
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}
