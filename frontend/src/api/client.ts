/**
 * api/client.ts
 *
 * Axios HTTP client for the Playto payout dashboard.
 *
 * Key design decisions:
 *   - JWT access token is stored in localStorage and attached to every request.
 *   - A response interceptor attempts a silent token refresh on 401, retries the
 *     failed request once, then redirects to login if the refresh also fails.
 *   - Idempotency keys use crypto.randomUUID() — native in modern browsers and
 *     sufficient for merchant-scoped UUID generation without an npm dependency.
 */

import axios, { type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'

import type {
  BankAccount,
  LedgerEntry,
  MerchantProfile,
  PaginatedResponse,
  PayoutRequest,
  TokenPair,
  TokenRefresh,
} from '../types'

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'
const TOKEN_STORAGE_KEY = 'playto.accessToken'
const REFRESH_STORAGE_KEY = 'playto.refreshToken'

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
})

// Request interceptor: attach Authorization header with the stored JWT access token.
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── 401 Token Refresh Interceptor ──────────────────────────────────────────
// Attempts a silent token refresh on 401, retries the original request once,
// then forces re-login if the refresh also fails. Concurrent 401s during
// refresh are queued and replayed when the new token arrives.

interface QueueItem {
  resolve: (token: string) => void
  reject: (error: unknown) => void
}

let isRefreshing = false
let failedQueue: QueueItem[] = []

function processQueue(error: unknown, token: string | null = null): void {
  for (const { resolve, reject } of failedQueue) {
    if (error) {
      reject(error)
    } else {
      resolve(token!)
    }
  }
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean }

    // Only attempt refresh for 401 errors that haven't already been retried.
    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error)
    }

    // If a refresh is already in progress, queue this request to retry after.
    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject })
      }).then((token) => {
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${token}`
        }
        return api(originalRequest)
      })
    }

    originalRequest._retry = true
    isRefreshing = true

    const refreshToken = localStorage.getItem(REFRESH_STORAGE_KEY)
    if (!refreshToken) {
      // No refresh token stored — force full re-login.
      isRefreshing = false
      clearTokens()
      window.location.reload()
      return Promise.reject(error)
    }

    try {
      // Exchange the refresh token for a new access token.
      const refreshResponse = await axios.post<TokenRefresh>(
        `${API_BASE_URL}/auth/token/refresh/`,
        { refresh: refreshToken },
      )
      const newAccessToken = refreshResponse.data.access
      localStorage.setItem(TOKEN_STORAGE_KEY, newAccessToken)

      // Retry the original request and flush the queue with the new token.
      if (originalRequest.headers) {
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
      }
      processQueue(null, newAccessToken)
      return api(originalRequest)
    } catch (refreshError) {
      // Refresh also failed — token pair is fully expired, force re-login.
      processQueue(refreshError, null)
      clearTokens()
      window.location.reload()
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  },
)

// ── Token Helpers ──────────────────────────────────────────────────────────

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function storeTokens(tokens: TokenPair): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, tokens.access)
  localStorage.setItem(REFRESH_STORAGE_KEY, tokens.refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  localStorage.removeItem(REFRESH_STORAGE_KEY)
}

/**
 * Generate a fresh UUID v4 idempotency key for a single form submission.
 * Each submit gets its own key so re-submitting a form after success creates
 * a new payout rather than replaying the previous one. (P2)
 */
export function makeIdempotencyKey(): string {
  return crypto.randomUUID()
}

// ── API Functions ──────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<TokenPair> {
  const response = await api.post<TokenPair>('/auth/token/', { username, password })
  storeTokens(response.data)
  return response.data
}

export async function signup(username: string, password: string): Promise<TokenPair> {
  const response = await api.post<TokenPair>('/auth/signup/', { username, password })
  storeTokens(response.data)
  return response.data
}

export async function seedAccount(personaId: number): Promise<void> {
  await api.post('/merchants/me/seed/', { persona_id: personaId })
}

export async function fetchMerchantProfile(): Promise<MerchantProfile> {
  const response = await api.get<MerchantProfile>('/merchants/me/')
  return response.data
}

export async function fetchBankAccounts(): Promise<BankAccount[]> {
  const response = await api.get<BankAccount[]>('/bank-accounts/')
  return response.data
}

export async function fetchPayouts(): Promise<PayoutRequest[]> {
  const response = await api.get<PayoutRequest[]>('/payouts/')
  return response.data
}

export async function fetchLedgerEntries(page = 1): Promise<PaginatedResponse<LedgerEntry>> {
  const response = await api.get<PaginatedResponse<LedgerEntry>>('/ledger/', { params: { page } })
  return response.data
}

export async function createPayout(
  payload: { amount_paise: number; bank_account_id: string },
  idempotencyKey: string,
): Promise<PayoutRequest> {
  const response = await api.post<PayoutRequest>('/payouts/', payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
  return response.data
}
