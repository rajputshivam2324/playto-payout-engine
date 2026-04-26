import { LogIn } from 'lucide-react'
import { type FormEvent, useState } from 'react'

import { login } from '../api/client'

interface LoginPanelProps {
  onLogin: () => void
}

export default function LoginPanel({ onLogin }: LoginPanelProps) {
  const [username, setUsername] = useState('rahul')
  const [password, setPassword] = useState('playto12345')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)
    try {
      await login(username, password)
      onLogin()
    } catch (requestError: unknown) {
      const axiosErr = requestError as { response?: { data?: { error?: { message?: string } } } }
      setError(axiosErr.response?.data?.error?.message ?? 'Unable to sign in.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <form className="grid gap-3.5 w-full max-w-[390px] p-6 border border-surface-500 rounded-lg bg-white shadow-[0_12px_34px_rgba(35,48,39,0.1)]" onSubmit={(e) => void handleSubmit(e)}>
        <div className="mb-1.5 text-brand-700 text-2xl font-extrabold leading-none">Playto</div>
        <label className="grid gap-1.5 text-surface-900 text-[13px] font-bold">
          <span>Username</span>
          <input
            className="w-full min-h-[42px] px-3 border border-surface-700 rounded-lg text-brand-900 bg-white outline-none font-[inherit] focus:border-brand-400 focus:shadow-[0_0_0_3px_rgba(25,135,94,0.12)]"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="grid gap-1.5 text-surface-900 text-[13px] font-bold">
          <span>Password</span>
          <input
            className="w-full min-h-[42px] px-3 border border-surface-700 rounded-lg text-brand-900 bg-white outline-none font-[inherit] focus:border-brand-400 focus:shadow-[0_0_0_3px_rgba(25,135,94,0.12)]"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error ? (
          <p className="m-0 p-2.5 border border-danger-border rounded-lg text-danger-fg bg-danger-bg text-[13px]">
            {error}
          </p>
        ) : null}
        <button
          className="inline-flex items-center justify-center gap-2 min-h-[42px] px-3.5 border border-brand-500 rounded-lg text-white bg-brand-500 font-[760] cursor-pointer hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-55"
          type="submit"
          disabled={isSubmitting}
        >
          <LogIn size={18} aria-hidden="true" />
          <span>{isSubmitting ? 'Signing in' : 'Sign in'}</span>
        </button>
      </form>
    </main>
  )
}
