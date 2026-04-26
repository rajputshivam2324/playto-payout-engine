import { type LucideIcon, CheckCircle2, CircleDashed, Clock3, XCircle } from 'lucide-react'

import { formatDateTime, formatRupees } from '../formatters'
import type { PayoutRequest, PayoutState } from '../types'

interface StateMeta {
  label: string
  icon: LucideIcon
  badgeClass: string
}

/**
 * Status badge metadata.
 * Spec: pending (gray), processing (blue, pulsing), completed (green), failed (red).
 * Processing icon uses animate-pulse-dot for the spec-required pulse animation.
 */
const stateMeta: Record<PayoutState, StateMeta> = {
  pending: {
    label: 'Pending',
    icon: Clock3,
    badgeClass: 'text-gray-600 bg-gray-100',
  },
  processing: {
    label: 'Processing',
    icon: CircleDashed,
    badgeClass: 'text-info-fg bg-info-bg',
  },
  completed: {
    label: 'Completed',
    icon: CheckCircle2,
    badgeClass: 'text-success-fg bg-success-bg',
  },
  failed: {
    label: 'Failed',
    icon: XCircle,
    badgeClass: 'text-danger-fg bg-danger-bg',
  },
}

interface PayoutTableProps {
  payouts: PayoutRequest[]
}

/**
 * Payout request table.
 *
 * Columns match the spec: Date · Amount · Bank Account · Status · Attempts.
 * The processing badge includes a pulse animation via CSS.
 * Polls every 3 seconds via usePayouts.
 */
export default function PayoutTable({ payouts }: PayoutTableProps) {
  return (
    <section className="border border-surface-500 rounded-lg bg-white shadow-[0_8px_24px_rgba(35,48,39,0.06)] overflow-hidden">
      <div className="flex items-center justify-between gap-3 p-4.5 border-b border-surface-400">
        <div>
          <p className="mb-1.5 text-surface-900 text-xs font-bold leading-tight uppercase">Payouts</p>
          <h2 className="m-0 text-brand-900 text-xl leading-tight">Requests</h2>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse min-w-[680px]">
          <thead>
            <tr>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Date</th>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Amount</th>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Bank Account</th>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Status</th>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Attempts</th>
              <th className="px-4.5 py-3.5 border-b border-surface-400 text-left text-surface-900 text-xs font-extrabold uppercase">Remarks</th>
            </tr>
          </thead>
          <tbody>
            {payouts.length ? (
              payouts.map((payout) => {
                const meta = stateMeta[payout.state]
                const Icon = meta.icon
                return (
                  <tr key={payout.id}>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-brand-900 text-[13px]">{formatDateTime(payout.created_at)}</td>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-brand-900 text-[13px]">{formatRupees(payout.amount_paise)}</td>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-brand-900 text-[13px]">{payout.bank_account_id ? payout.bank_account_id.slice(-8) : '—'}</td>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-[13px]">
                      <span className={`inline-flex items-center gap-1.5 min-h-7 px-2.5 rounded-lg font-[760] whitespace-nowrap ${meta.badgeClass}`}>
                        <Icon size={15} className={payout.state === 'processing' ? 'animate-pulse-dot' : ''} aria-hidden="true" />
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-brand-900 text-[13px]">{payout.attempt_count}</td>
                    <td className="px-4.5 py-3.5 border-b border-surface-300 text-left text-brand-900 text-[13px]">{payout.failure_reason ?? '—'}</td>
                  </tr>
                )
              })
            ) : (
              <tr>
                <td colSpan={6} className="py-5.5 px-4.5 text-surface-900 text-center">
                  No payouts yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
