import { useCallback, useState } from 'react'

import { fetchLedgerEntries } from '../api/client'
import type { LedgerEntry, PaginatedResponse } from '../types'
import { usePollingResource, type PollingResourceResult } from './usePollingResource'

export interface LedgerResource extends PollingResourceResult<PaginatedResponse<LedgerEntry>> {
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
}

/** Poll ledger entries every 8 seconds with page-number pagination. */
export function useLedger(enabled: boolean): LedgerResource {
  const [page, setPage] = useState(1)
  const fetcher = useCallback(() => fetchLedgerEntries(page), [page])
  const resource = usePollingResource(fetcher, { enabled, intervalMs: 8000 })
  return { ...resource, page, setPage }
}
