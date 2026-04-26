/**
 * hooks/usePollingResource.ts
 *
 * Generic polling hook that fetches data on an interval and supports manual refresh.
 * Every polling hook in the dashboard (balance, payouts, ledger) is built on this.
 */

import { useCallback, useEffect, useState } from 'react'

export interface PollingResourceResult<T> {
  data: T | null
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<T | null>
  updatedAt: Date | null
}

interface PollingOptions {
  enabled?: boolean
  /** Polling interval in milliseconds. Spec: balance=5000, payouts=3000. */
  intervalMs?: number
}

export function usePollingResource<T>(
  fetcher: () => Promise<T>,
  options: PollingOptions = {},
): PollingResourceResult<T> {
  const { enabled = true, intervalMs = 5000 } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(enabled))
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const refresh = useCallback(async (): Promise<T | null> => {
    if (!enabled) {
      return null
    }
    try {
      setError(null)
      const result = await fetcher()
      setData(result)
      setUpdatedAt(new Date())
      return result
    } catch (requestError) {
      setError(requestError as Error)
      return null
    } finally {
      setIsLoading(false)
    }
  }, [enabled, fetcher])

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false)
      return undefined
    }

    let cancelled = false
    const run = async () => {
      if (!cancelled) {
        await refresh()
      }
    }

    void run()
    const timerId = window.setInterval(() => void run(), intervalMs)

    return () => {
      cancelled = true
      window.clearInterval(timerId)
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, isLoading, refresh, updatedAt }
}
