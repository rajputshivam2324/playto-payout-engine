import { Clock, IndianRupee, RefreshCw, WalletCards } from 'lucide-react'

import { formatDateTime, formatRupees } from '../formatters'
import type { MerchantProfile } from '../types'

interface BalanceCardProps {
  merchant: MerchantProfile | null
  isLoading: boolean
  onRefresh: () => Promise<MerchantProfile | null>
  updatedAt: Date | null
}

/**
 * Shows available balance in rupees and held balance separately with a tooltip.
 * Polls GET /api/v1/merchants/me/ every 5 seconds via useBalance.
 */
export default function BalanceCard({ merchant, isLoading, onRefresh, updatedAt }: BalanceCardProps) {
  const available = merchant?.available_balance_paise ?? 0
  const held = merchant?.held_balance_paise ?? 0

  if (!merchant && isLoading) {
    // Skeleton loader shown on first load before any data arrives.
    return (
      <section className="grid grid-cols-[minmax(0,1fr)_auto] gap-5 items-end p-6 border border-surface-800 rounded-lg bg-white shadow-[0_10px_32px_rgba(35,48,39,0.08)]">
        <div>
          <p className="mb-1.5 text-surface-900 text-xs font-bold leading-tight uppercase">Available balance</p>
          <div className="flex items-center gap-2 text-brand-800">
            <IndianRupee size={30} aria-hidden="true" />
            <span className="animate-shimmer min-w-45 min-h-11 rounded-md">&nbsp;</span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2 mt-3 text-surface-900 text-sm">
            <span className="animate-shimmer min-w-30 min-h-4.5 rounded-md">&nbsp;</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="animate-shimmer inline-flex items-center min-h-8.5 min-w-22 gap-1.5 px-2.5 border border-held-border rounded-lg">&nbsp;</div>
        </div>
      </section>
    )
  }

  return (
    <section className="grid grid-cols-[minmax(0,1fr)_auto] gap-5 items-end p-6 border border-surface-800 rounded-lg bg-white shadow-[0_10px_32px_rgba(35,48,39,0.08)]">
      <div>
        <p className="mb-1.5 text-surface-900 text-xs font-bold leading-tight uppercase">Available balance</p>
        <div className="flex items-center gap-2 text-brand-800">
          <IndianRupee size={30} aria-hidden="true" />
          <span className="text-[44px] font-[760] leading-none">{formatRupees(available)}</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-2 mt-3 text-surface-900 text-sm">
          <span>{merchant?.name ?? 'Playto merchant'}</span>
          <span>{merchant?.email ?? 'Signed in'}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div
          className="inline-flex items-center min-h-8.5 gap-1.5 px-2.5 border border-held-border rounded-lg text-held-fg bg-held-bg text-[13px] whitespace-nowrap"
          title="Funds held for pending payouts"
        >
          <WalletCards size={18} aria-hidden="true" />
          <span>Held {formatRupees(held)}</span>
        </div>
        <div className="inline-flex items-center min-h-8.5 gap-1.5 px-2.5 border border-surface-600 rounded-lg text-brand-900 bg-surface-50 text-[13px] whitespace-nowrap">
          <Clock size={16} aria-hidden="true" />
          <span>{updatedAt ? formatDateTime(updatedAt.toISOString()) : 'Waiting'}</span>
        </div>
        <button
          className="inline-grid place-items-center w-9.5 h-9.5 border border-surface-700 rounded-lg text-brand-900 bg-white hover:border-brand-300 hover:text-brand-700 cursor-pointer"
          type="button"
          onClick={() => void onRefresh()}
          title="Refresh balances"
        >
          <RefreshCw size={18} className={isLoading ? 'animate-spin-slow' : ''} aria-hidden="true" />
        </button>
      </div>
    </section>
  )
}
