import { useCallback, useState } from 'react'

import { clearTokens, getStoredToken } from './api/client'
import BalanceCard from './components/BalanceCard'
import LedgerFeed from './components/LedgerFeed'
import LoginPanel from './components/LoginPanel'
import PayoutForm from './components/PayoutForm'
import PayoutTable from './components/PayoutTable'
import TopBar from './components/TopBar'
import { useBalance } from './hooks/useBalance'
import { useBankAccounts } from './hooks/useBankAccounts'
import { useLedger } from './hooks/useLedger'
import { usePayouts } from './hooks/usePayouts'

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getStoredToken()))
  const balance = useBalance(isAuthenticated)
  const accounts = useBankAccounts(isAuthenticated)
  const payouts = usePayouts(isAuthenticated)
  const ledger = useLedger(isAuthenticated)

  const refreshDashboard = useCallback(async () => {
    await Promise.all([balance.refresh(), accounts.refresh(), payouts.refresh(), ledger.refresh()])
  }, [accounts, balance, ledger, payouts])

  const handleLogout = useCallback(() => {
    clearTokens()
    setIsAuthenticated(false)
  }, [])

  if (!isAuthenticated) {
    return <LoginPanel onLogin={() => setIsAuthenticated(true)} />
  }

  const merchant = balance.data
  const bankAccounts = accounts.data ?? []
  const payoutRows = payouts.data ?? []
  const isRefreshing = balance.isLoading || accounts.isLoading || payouts.isLoading || ledger.isLoading

  return (
    <main className="w-[min(1180px,calc(100%-32px))] mx-auto py-5">
      <TopBar merchant={merchant} onRefresh={refreshDashboard} onLogout={handleLogout} isRefreshing={isRefreshing} />

      <BalanceCard merchant={merchant} isLoading={balance.isLoading} onRefresh={balance.refresh} updatedAt={balance.updatedAt} />

      <div className="grid grid-cols-[minmax(280px,360px)_minmax(0,1fr)] gap-4 mt-4 items-start max-md:grid-cols-1">
        <PayoutForm accounts={bankAccounts} availablePaise={merchant?.available_balance_paise ?? 0} onCreated={refreshDashboard} />
        <PayoutTable payouts={payoutRows} />
        <LedgerFeed ledger={ledger.data} page={ledger.page} setPage={ledger.setPage} />
      </div>

      {balance.error ?? accounts.error ?? payouts.error ?? ledger.error ? (
        <div className="mt-4 p-2.5 border border-danger-border rounded-lg text-danger-fg bg-danger-bg text-[13px]">
          The dashboard could not refresh. Sign in again if the session expired.
        </div>
      ) : null}
    </main>
  )
}
