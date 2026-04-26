import { useCallback } from 'react'

import { fetchMerchantProfile } from '../api/client'
import type { MerchantProfile } from '../types'
import { usePollingResource, type PollingResourceResult } from './usePollingResource'

/** Poll the merchant profile every 5 seconds for live balance updates. */
export function useBalance(enabled: boolean): PollingResourceResult<MerchantProfile> {
  const fetcher = useCallback(() => fetchMerchantProfile(), [])
  return usePollingResource(fetcher, { enabled, intervalMs: 5000 })
}
