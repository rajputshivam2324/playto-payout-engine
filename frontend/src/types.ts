/**
 * types.ts
 *
 * Shared type definitions for the Playto payout dashboard.
 *
 * These mirror the JSON shapes returned by the Django REST API
 * and enforce type safety across all components and hooks.
 */

/** Merchant profile returned by GET /api/v1/merchants/me/ */
export interface MerchantProfile {
  id: string
  name: string
  email: string
  created_at: string
  /** Available balance in paise — SUM(CREDIT) - SUM(DEBIT). (P3) */
  available_balance_paise: number
  /** Funds currently held by pending/processing payouts, in paise. */
  held_balance_paise: number
  /** Flag for UI to show seed selection screen */
  has_seeded_data?: boolean
}

/** Bank account returned by GET /api/v1/bank-accounts/ — account number is always masked. */
export interface BankAccount {
  id: string
  account_holder: string
  /** Masked account number — only last 4 digits visible. Full number is never sent over the wire. */
  account_number_masked: string
  ifsc_code: string
  is_default: boolean
  created_at: string
}

/** Payout state matching the Django PayoutRequest.STATE_CHOICES. */
export type PayoutState = 'pending' | 'processing' | 'completed' | 'failed'

/** Payout request returned by GET /api/v1/payouts/ */
export interface PayoutRequest {
  id: string
  amount_paise: number
  state: PayoutState
  bank_account_id: string
  attempt_count: number
  failure_reason: string | null
  created_at: string
  updated_at: string
}

/** Ledger entry returned by GET /api/v1/ledger/ */
export interface LedgerEntry {
  id: string
  entry_type: 'CREDIT' | 'DEBIT'
  amount_paise: number
  reference_id: string
  description: string
  /** Resolved payout state for DEBIT entries, null for credits/non-payout debits. */
  payout_state: PayoutState | null
  created_at: string
}

/** DRF paginated response wrapper. */
export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

/** Stripe-style structured error body returned by all API error responses. (P6) */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    param: string | null
  }
}

/** JWT token pair returned by POST /api/v1/auth/token/ */
export interface TokenPair {
  access: string
  refresh: string
}

/** Token refresh response from POST /api/v1/auth/token/refresh/ */
export interface TokenRefresh {
  access: string
}
