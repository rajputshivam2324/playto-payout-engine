import { ArrowDownRight, ArrowUpRight, ChevronLeft, ChevronRight } from 'lucide-react'

import { formatDateTime, formatRupees } from '../formatters'
import type { LedgerEntry, PaginatedResponse } from '../types'

interface LedgerFeedProps {
  ledger: PaginatedResponse<LedgerEntry> | null
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
}

/**
 * Derive a display label for a ledger entry.
 * For DEBIT entries linked to a payout, replace the static "Payout hold"
 * description with the current payout state (e.g. "Payout completed").
 */
function ledgerLabel(entry: LedgerEntry): string {
  if (entry.payout_state && entry.entry_type === 'DEBIT') {
    // Extract the destination from the original immutable description (e.g. "Payout hold to ******5501")
    const dest = entry.description.match(/\*{6}\d{4}/)?.[0] ?? ''
    const stateLabels: Record<string, string> = {
      pending: 'Payout hold',
      processing: 'Payout processing',
      completed: 'Payout settled',
      failed: 'Payout failed (refunded)',
    }
    const label = stateLabels[entry.payout_state] ?? entry.description
    return dest ? `${label} to ${dest}` : label
  }
  return entry.description
}

/**
 * Recent ledger entries with pagination.
 * Credits shown in green with ↑ arrow, debits in red with ↓ arrow. (Spec Phase 5)
 */
export default function LedgerFeed({ ledger, page, setPage }: LedgerFeedProps) {
  const entries = ledger?.results ?? []
  const hasPrevious = Boolean(ledger?.previous)
  const hasNext = Boolean(ledger?.next)

  return (
    <section className="border border-surface-500 rounded-lg bg-white shadow-[0_8px_24px_rgba(35,48,39,0.06)] overflow-hidden col-span-full">
      <div className="flex items-center justify-between gap-3 p-4.5 border-b border-surface-400">
        <div>
          <p className="mb-1.5 text-surface-900 text-xs font-bold leading-tight uppercase">Ledger</p>
          <h2 className="m-0 text-brand-900 text-xl leading-tight">Entries</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="inline-grid place-items-center w-7.5 h-7.5 border border-surface-700 rounded-lg text-brand-900 bg-white hover:border-brand-300 hover:text-brand-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-55"
            type="button"
            disabled={!hasPrevious}
            onClick={() => setPage(Math.max(1, page - 1))}
            title="Previous page"
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className="min-w-4.5 text-center text-surface-900 text-[13px] font-extrabold">{page}</span>
          <button
            className="inline-grid place-items-center w-7.5 h-7.5 border border-surface-700 rounded-lg text-brand-900 bg-white hover:border-brand-300 hover:text-brand-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-55"
            type="button"
            disabled={!hasNext}
            onClick={() => setPage(page + 1)}
            title="Next page"
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid">
        {entries.length ? (
          entries.map((entry) => {
            const isCredit = entry.entry_type === 'CREDIT'
            // Credits use ↑ arrow (incoming funds), debits use ↓ arrow (outgoing holds).
            const Icon = isCredit ? ArrowUpRight : ArrowDownRight
            return (
              <div className="grid grid-cols-[34px_minmax(0,1fr)_auto] gap-3 items-center px-4.5 py-3.5 border-b border-surface-300" key={entry.id}>
                <span className={`grid place-items-center w-8.5 h-8.5 rounded-lg ${isCredit ? 'text-success-fg bg-success-bg' : 'text-danger-fg bg-danger-bg'}`}>
                  <Icon size={16} aria-hidden="true" />
                </span>
                <div className="grid gap-0.5 min-w-0">
                  <strong className="overflow-hidden text-brand-900 text-sm text-ellipsis whitespace-nowrap">{ledgerLabel(entry)}</strong>
                  <span className="text-surface-900 text-xs">{formatDateTime(entry.created_at)}</span>
                </div>
                <b className={isCredit ? 'text-success-fg' : 'text-danger-fg'}>
                  {isCredit ? '+' : '-'}
                  {formatRupees(entry.amount_paise)}
                </b>
              </div>
            )
          })
        ) : (
          <div className="py-5.5 px-4.5 text-surface-900 text-center">No ledger entries</div>
        )}
      </div>
    </section>
  )
}
