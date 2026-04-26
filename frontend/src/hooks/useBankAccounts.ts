import { useCallback } from 'react'

import { fetchBankAccounts } from '../api/client'
import type { BankAccount } from '../types'
import { usePollingResource, type PollingResourceResult } from './usePollingResource'

/** Poll bank accounts every 15 seconds — they change infrequently. */
export function useBankAccounts(enabled: boolean): PollingResourceResult<BankAccount[]> {
  const fetcher = useCallback(() => fetchBankAccounts(), [])
  return usePollingResource(fetcher, { enabled, intervalMs: 15000 })
}
