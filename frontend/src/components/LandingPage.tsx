import { LogIn, UserPlus } from 'lucide-react'
import { type FormEvent, useState } from 'react'

import { login, signup } from '../api/client'

interface LandingPageProps {
  onLogin: () => void
}

export default function LandingPage({ onLogin }: LandingPageProps) {
  const [isLoginMode, setIsLoginMode] = useState(true)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)
    try {
      if (isLoginMode) {
        await login(username || 'rahul', password || 'playto12345')
      } else {
        await signup(username, password)
      }
      onLogin()
    } catch (requestError: unknown) {
      const axiosErr = requestError as { response?: { data?: { error?: { message?: string } } } }
      setError(axiosErr.response?.data?.error?.message ?? (isLoginMode ? 'Unable to sign in.' : 'Unable to sign up.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <div className="grid md:grid-cols-2 gap-12 max-w-5xl w-full items-center">
        
        {/* Left Side: Hero / Brand */}
        <div className="max-md:text-center space-y-6">
          <div className="text-brand-700 text-5xl font-black tracking-tight leading-none bg-clip-text text-transparent bg-gradient-to-br from-brand-600 to-brand-400 inline-block">
            Playto
          </div>
          <h1 className="text-4xl text-brand-900 font-extrabold tracking-tight leading-tight">
            The minimal, lightning-fast payout engine.
          </h1>
          <p className="text-surface-900 text-lg font-medium max-w-md max-md:mx-auto leading-relaxed">
            Manage your ledgers, orchestrate payouts, and scale your business without the clutter. Designed for speed, precision, and elegance.
          </p>
          <div className="flex gap-4 items-center max-md:justify-center">
            <div className="flex -space-x-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="w-10 h-10 rounded-full border-2 border-white bg-surface-200 flex items-center justify-center text-xs font-bold text-surface-900 shadow-sm">
                  {['RS', 'AI', 'VM'][i-1]}
                </div>
              ))}
            </div>
            <span className="text-sm font-bold text-surface-900">+10,000 merchants</span>
          </div>
        </div>

        {/* Right Side: Auth Form */}
        <div className="w-full max-w-[420px] mx-auto p-8 rounded-2xl bg-white shadow-[0_24px_64px_rgba(25,135,94,0.06)] border border-surface-200 relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-brand-400 to-brand-600"></div>
          
          <div className="flex gap-4 mb-8">
            <button
              type="button"
              onClick={() => { setIsLoginMode(true); setError(''); }}
              className={`flex-1 pb-3 text-sm font-bold border-b-2 transition-colors ${
                isLoginMode ? 'border-brand-500 text-brand-700' : 'border-surface-200 text-surface-900 hover:text-brand-600'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => { setIsLoginMode(false); setError(''); }}
              className={`flex-1 pb-3 text-sm font-bold border-b-2 transition-colors ${
                !isLoginMode ? 'border-brand-500 text-brand-700' : 'border-surface-200 text-surface-900 hover:text-brand-600'
              }`}
            >
              Create Account
            </button>
          </div>

          <form className="grid gap-5" onSubmit={(e) => void handleSubmit(e)}>
            <label className="grid gap-2 text-surface-900 text-sm font-bold">
              <span>Username</span>
              <input
                className="w-full h-11 px-4 border border-surface-400 rounded-xl text-brand-900 bg-surface-50 outline-none font-medium text-[15px] transition-all focus:bg-white focus:border-brand-400 focus:ring-4 focus:ring-brand-400/10 placeholder:text-surface-900/50"
                value={username}
                placeholder={isLoginMode ? 'e.g. rahul' : 'Enter username'}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </label>
            <label className="grid gap-2 text-surface-900 text-sm font-bold">
              <span>Password</span>
              <input
                className="w-full h-11 px-4 border border-surface-400 rounded-xl text-brand-900 bg-surface-50 outline-none font-medium text-[15px] transition-all focus:bg-white focus:border-brand-400 focus:ring-4 focus:ring-brand-400/10 placeholder:text-surface-900/50"
                type="password"
                placeholder={isLoginMode ? 'e.g. playto12345' : 'At least 8 characters'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={isLoginMode ? 'current-password' : 'new-password'}
              />
            </label>
            
            {error ? (
              <div className="p-3 border border-danger-border rounded-xl text-danger-fg bg-danger-bg text-sm font-medium animate-in fade-in slide-in-from-top-1">
                {error}
              </div>
            ) : null}
            
            <button
              className="mt-2 w-full flex items-center justify-center gap-2 h-12 px-4 rounded-xl text-white bg-brand-500 font-extrabold text-[15px] transition-all hover:bg-brand-600 hover:shadow-lg hover:shadow-brand-500/25 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100"
              type="submit"
              disabled={isSubmitting}
            >
              {isLoginMode ? <LogIn size={18} aria-hidden="true" /> : <UserPlus size={18} aria-hidden="true" />}
              <span>{isSubmitting ? 'Please wait...' : isLoginMode ? 'Sign In' : 'Create Account'}</span>
            </button>
          </form>
        </div>
      </div>
    </main>
  )
}
