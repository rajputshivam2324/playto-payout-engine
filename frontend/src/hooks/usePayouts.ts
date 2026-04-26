import { useCallback } from 'react'

import { fetchPayouts } from '../api/client'
import type { PayoutRequest } from '../types'
import { usePollingResource, type PollingResourceResult } from './usePollingResource'

/**
 * Poll payouts every 3 seconds so processing→completed/failed transitions
 * from background workers appear promptly in the dashboard. (P7)
 */
export function usePayouts(enabled: boolean): PollingResourceResult<PayoutRequest[]> {
  const fetcher = useCallback(() => fetchPayouts(), [])
  return usePollingResource(fetcher, { enabled, intervalMs: 3000 })
}
