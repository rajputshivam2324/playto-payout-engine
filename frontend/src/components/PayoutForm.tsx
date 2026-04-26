import { SendHorizonal } from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useState } from 'react'

import { createPayout, makeIdempotencyKey } from '../api/client'
import { formatRupees } from '../formatters'
import type { BankAccount } from '../types'

interface PayoutFormProps {
  accounts: BankAccount[]
  availablePaise: number
  onCreated: () => Promise<void>
}

/**
 * Convert a rupee string from the input field to integer paise.
 * Uses Math.round after float multiplication to snap to the nearest integer.
 * This is the only place float→int conversion happens in the frontend. (P9)
 */
function rupeesToPaise(value: string): number {
  const rupees = Number.parseFloat(value)
  if (Number.isNaN(rupees)) {
    return 0
  }
  // Integer multiplication — the result is rounded to the nearest paise to avoid float artifacts.
  return Math.round(rupees * 100)
}

export default function PayoutForm({ accounts, availablePaise, onCreated }: PayoutFormProps) {
  const defaultAccount = useMemo(
    () => accounts.find((account) => account.is_default) ?? accounts[0],
    [accounts],
  )
  const [amountRupees, setAmountRupees] = useState('')
  const [bankAccountId, setBankAccountId] = useState('')
  const [inlineError, setInlineError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (!bankAccountId && defaultAccount) {
      setBankAccountId(defaultAccount.id)
    }
  }, [bankAccountId, defaultAccount])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setInlineError('')
    const amountPaise = rupeesToPaise(amountRupees)
    if (amountPaise <= 0) {
      setInlineError('Enter an amount greater than zero.')
      return
    }
    setIsSubmitting(true)
    try {
      // Each submission generates a fresh UUID so re-submitting creates a new payout. (P2)
      const idempotencyKey = makeIdempotencyKey()
      await createPayout({ amount_paise: amountPaise, bank_account_id: bankAccountId }, idempotencyKey)
      setAmountRupees('')
      await onCreated()
    } catch (requestError: unknown) {
      const axiosErr = requestError as { response?: { data?: { error?: { code?: string; message?: string } } } }
      const errorCode = axiosErr.response?.data?.error?.code
      if (errorCode === 'insufficient_funds') {
        // 402 response shows "Insufficient funds" inline in the form, not a toast. (P6)
        setInlineError('Insufficient funds for this payout.')
      } else if (errorCode === 'request_in_progress') {
        // 409 response shows "Request in progress, please wait" inline. (P6)
        setInlineError('Request in progress, please wait.')
      } else {
        setInlineError(axiosErr.response?.data?.error?.message ?? 'Payout could not be created.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="border border-surface-500 rounded-lg bg-white shadow-[0_8px_24px_rgba(35,48,39,0.06)] p-4.5">
      <div className="flex items-center justify-between gap-3 pb-4">
        <div>
          <p className="mb-1.5 text-surface-900 text-xs font-bold leading-tight uppercase">New payout</p>
          <h2 className="m-0 text-brand-900 text-xl leading-tight">Move funds</h2>
        </div>
        <span className="inline-flex items-center min-h-8.5 gap-1.5 px-2.5 border border-surface-600 rounded-lg text-brand-900 bg-surface-50 text-[13px] whitespace-nowrap">
          {formatRupees(availablePaise)}
        </span>
      </div>

      <form className="grid gap-3.5" onSubmit={(e) => void handleSubmit(e)}>
        <label className="grid gap-1.5 text-surface-900 text-[13px] font-bold">
          <span>Amount</span>
          <div className="grid grid-cols-[34px_minmax(0,1fr)] items-center border border-surface-700 rounded-lg bg-white overflow-hidden">
            <span className="grid place-items-center min-h-[42px] text-surface-900 bg-surface-200">₹</span>
            <input
              className="w-full min-h-[42px] px-3 border-0 rounded-none text-brand-900 bg-white outline-none font-[inherit] shadow-none focus:ring-0"
              inputMode="decimal"
              placeholder="0.00"
              value={amountRupees}
              onChange={(event) => setAmountRupees(event.target.value)}
            />
          </div>
        </label>

        <label className="grid gap-1.5 text-surface-900 text-[13px] font-bold">
          <span>Destination</span>
          <select
            className="w-full min-h-[42px] pl-3 pr-9 border border-surface-700 rounded-lg text-brand-900 bg-white outline-none font-[inherit] focus:border-brand-400 focus:shadow-[0_0_0_3px_rgba(25,135,94,0.12)]"
            value={bankAccountId}
            onChange={(event) => setBankAccountId(event.target.value)}
            disabled={!accounts.length}
          >
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.account_holder} — {account.account_number_masked} ({account.ifsc_code})
              </option>
            ))}
          </select>
        </label>

        {inlineError ? (
          <p className="m-0 p-2.5 border border-danger-border rounded-lg text-danger-fg bg-danger-bg text-[13px]">
            {inlineError}
          </p>
        ) : null}

        <button
          className="inline-flex items-center justify-center gap-2 min-h-[42px] px-3.5 border border-brand-500 rounded-lg text-white bg-brand-500 font-[760] cursor-pointer hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-55"
          type="submit"
          disabled={isSubmitting || !accounts.length}
        >
          <SendHorizonal size={18} aria-hidden="true" />
          <span>{isSubmitting ? 'Creating' : 'Create payout'}</span>
        </button>
      </form>
    </section>
  )
}
