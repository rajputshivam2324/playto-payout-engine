import { ShoppingBag, Code, Cloud, PenTool, TrendingUp, ArrowRight, Loader2 } from 'lucide-react'
import { useState } from 'react'

import { seedAccount } from '../api/client'

interface SeedSelectionProps {
  onSeeded: () => void
}

const PERSONAS = [
  { id: 1, title: 'Boutique E-commerce', desc: 'High volume, smaller transactions', icon: ShoppingBag },
  { id: 2, title: 'Freelance Developer', desc: 'Medium volume, milestone payments', icon: Code },
  { id: 3, title: 'SaaS Startup', desc: 'High volume, subscription renewals', icon: Cloud },
  { id: 4, title: 'Design Agency', desc: 'Low volume, large retainer fees', icon: PenTool },
  { id: 5, title: 'Consulting Firm', desc: 'Very low volume, massive corporate contracts', icon: TrendingUp },
]

export default function SeedSelection({ onSeeded }: SeedSelectionProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function handleSeed() {
    if (!selectedId) return
    setIsSubmitting(true)
    setError('')
    try {
      await seedAccount(selectedId)
      onSeeded()
    } catch (err: unknown) {
      console.error(err)
      setError('Failed to seed account. Please try again.')
      setIsSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen bg-surface-50 p-6 flex flex-col items-center justify-center">
      <div className="max-w-4xl w-full">
        <div className="text-center mb-12">
          <h1 className="text-3xl font-extrabold text-brand-900 mb-4">Choose your Merchant Profile</h1>
          <p className="text-surface-900 text-lg max-w-2xl mx-auto">
            We will populate your dashboard with realistic transaction history and mock bank accounts based on your selection.
          </p>
        </div>

        {error && (
          <div className="mb-8 p-4 border border-danger-border rounded-xl text-danger-fg bg-danger-bg text-sm font-bold max-w-lg mx-auto text-center">
            {error}
          </div>
        )}

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {PERSONAS.map((p) => {
            const isSelected = selectedId === p.id
            const Icon = p.icon
            return (
              <button
                key={p.id}
                onClick={() => setSelectedId(p.id)}
                disabled={isSubmitting}
                className={`text-left p-6 rounded-2xl border-2 transition-all duration-200 outline-none
                  ${isSelected
                    ? 'bg-white border-brand-500 shadow-[0_8px_24px_rgba(25,135,94,0.12)] -translate-y-1'
                    : 'bg-white border-surface-200 shadow-sm hover:border-surface-400 hover:shadow-md'
                  }
                  ${isSubmitting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 transition-colors
                  ${isSelected ? 'bg-brand-50 text-brand-600' : 'bg-surface-100 text-surface-900'}
                `}>
                  <Icon size={24} strokeWidth={2.5} />
                </div>
                <h3 className={`text-[17px] font-extrabold mb-2 ${isSelected ? 'text-brand-900' : 'text-surface-900'}`}>
                  {p.title}
                </h3>
                <p className="text-sm font-medium text-surface-900/80 leading-relaxed">
                  {p.desc}
                </p>
              </button>
            )
          })}
        </div>

        <div className="flex justify-center">
          <button
            onClick={() => void handleSeed()}
            disabled={!selectedId || isSubmitting}
            className="group flex items-center gap-3 px-8 h-14 rounded-full bg-brand-900 text-white font-bold text-lg transition-all hover:bg-brand-800 hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="animate-spin" size={20} />
                Building your dashboard...
              </>
            ) : (
              <>
                Continue to Dashboard
                <ArrowRight size={20} className="transition-transform group-hover:translate-x-1" />
              </>
            )}
          </button>
        </div>
      </div>
    </main>
  )
}
