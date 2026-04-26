import { LogOut, RefreshCw } from 'lucide-react'

import type { MerchantProfile } from '../types'

interface TopBarProps {
  merchant: MerchantProfile | null
  onRefresh: () => Promise<void>
  onLogout: () => void
  isRefreshing: boolean
}

export default function TopBar({ merchant, onRefresh, onLogout, isRefreshing }: TopBarProps) {
  return (
    <header className="flex items-center justify-between min-h-12 mb-4.5">
      <div className="flex items-baseline gap-3">
        <strong className="text-brand-700 text-2xl leading-none">Playto</strong>
        <span className="text-surface-900 text-sm">{merchant?.name ?? 'Payouts'}</span>
      </div>
      <div className="flex items-center gap-2">
        <button
          className="inline-grid place-items-center w-9.5 h-9.5 border border-surface-700 rounded-lg text-brand-900 bg-white hover:border-brand-300 hover:text-brand-700 cursor-pointer"
          type="button"
          onClick={() => void onRefresh()}
          title="Refresh dashboard"
        >
          <RefreshCw size={18} className={isRefreshing ? 'animate-spin-slow' : ''} aria-hidden="true" />
        </button>
        <button
          className="inline-grid place-items-center w-9.5 h-9.5 border border-surface-700 rounded-lg text-brand-900 bg-white hover:border-brand-300 hover:text-brand-700 cursor-pointer"
          type="button"
          onClick={onLogout}
          title="Sign out"
        >
          <LogOut size={18} aria-hidden="true" />
        </button>
      </div>
    </header>
  )
}
