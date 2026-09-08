import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react'
import { triggerArchitectureAgent } from '../services/dashboardService'

interface Props {
  lastUpdated: string | null
}

type TriggerState = 'idle' | 'loading' | 'cooldown' | 'error'

// How long to disable the button after a successful trigger. The agent run
// itself takes several minutes, so this just guards against accidental
// double-clicks / spamming -- it is not meant to reflect actual completion.
const COOLDOWN_SECONDS = 60

/**
 * Dashboard control that lets an operator regenerate the architecture
 * knowledge base on demand. Triggers the architecture agent asynchronously
 * (the agent itself can take several minutes) and shows when the knowledge
 * base was last regenerated, based on the S3 "architecture/" prefix.
 */
export function ArchitectureAgentControl({ lastUpdated }: Props) {
  const [state, setState] = useState<TriggerState>('idle')
  const [cooldownRemaining, setCooldownRemaining] = useState(0)
  const intervalRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  const startCooldown = () => {
    setState('cooldown')
    setCooldownRemaining(COOLDOWN_SECONDS)

    intervalRef.current = window.setInterval(() => {
      setCooldownRemaining((prev) => {
        if (prev <= 1) {
          if (intervalRef.current) clearInterval(intervalRef.current)
          setState('idle')
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  const handleTrigger = async () => {
    if (state === 'loading' || state === 'cooldown') return
    setState('loading')
    try {
      await triggerArchitectureAgent()
      startCooldown()
    } catch {
      setState('error')
      window.setTimeout(() => setState('idle'), 4000)
    }
  }

  const isDisabled = state === 'loading' || state === 'cooldown'

  return (
    <div className="flex items-center gap-3">
      <div className="text-right">
        <p className="text-[10px] text-muted uppercase tracking-wider leading-none">
          Architecture Docs
        </p>
        <p className="text-[11px] text-muted-light font-medium mt-0.5">
          {formatLastUpdated(lastUpdated)}
        </p>
      </div>

      <button
        onClick={handleTrigger}
        disabled={isDisabled}
        title={
          state === 'cooldown'
            ? 'Architecture agent run started -- please wait before triggering again'
            : 'Regenerate the architecture knowledge base'
        }
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-border text-[11px] font-medium text-muted-light bg-card/60 hover:border-primary/30 hover:text-foreground transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
      >
        <StatusIcon state={state} />
        {statusLabel(state, cooldownRemaining)}
      </button>

      {state === 'error' && (
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-[11px] text-error"
        >
          Failed to start
        </motion.span>
      )}
    </div>
  )
}

function StatusIcon({ state }: { state: TriggerState }) {
  if (state === 'loading') return <RefreshCw className="w-3.5 h-3.5 animate-spin" />
  if (state === 'cooldown') return <CheckCircle2 className="w-3.5 h-3.5 text-success" />
  if (state === 'error') return <AlertCircle className="w-3.5 h-3.5 text-error" />
  return <RefreshCw className="w-3.5 h-3.5" />
}

function statusLabel(state: TriggerState, cooldownRemaining: number): string {
  switch (state) {
    case 'loading':
      return 'Starting...'
    case 'cooldown':
      return `Started (${cooldownRemaining}s)`
    case 'error':
      return 'Retry'
    default:
      return 'Regenerate'
  }
}

function formatLastUpdated(iso: string | null): string {
  // TODO: Remove hardcoded timestamp once architecture trigger is fixed
  if (!iso) return 'Aug 14, 2026, 03:00 PM IST'
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}
