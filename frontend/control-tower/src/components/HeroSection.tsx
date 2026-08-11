import { motion } from 'framer-motion'
import { Brain, Code2, Shield, Rocket, Clock, CheckCircle, Loader, Circle, TrendingUp } from 'lucide-react'
import type { WorkflowEvent, WorkflowStage } from '../types'

interface Props {
  workflow: WorkflowEvent
}

const agentLabels: Record<string, string> = {
  planning: 'Solution Architect',
  architecture: 'Solution Architect',
  development: 'Senior Software Engineer',
  validation: 'Quality Assurance Engineer',
  release: 'DevOps Engineer',
}

const stageIcons: Record<string, React.ReactNode> = {
  planning: <Brain className="w-5 h-5" />,
  development: <Code2 className="w-5 h-5" />,
  validation: <Shield className="w-5 h-5" />,
  release: <Rocket className="w-5 h-5" />,
}

export function HeroSection({ workflow }: Props) {
  const elapsed = getElapsed(workflow.startedAt)
  const currentAgent = agentLabels[workflow.currentAgent] || workflow.currentAgent || '—'
  const confidence = (workflow as any).confidence ?? workflow.progress ?? 0
  const eta = (workflow as any).eta || estimateEta(workflow.progress)

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
      className="relative overflow-hidden rounded-3xl border border-border bg-card/60 backdrop-blur-md"
    >
      <div className="absolute inset-0 bg-radial-fade pointer-events-none" />
      <div className="absolute inset-0 bg-grid pointer-events-none opacity-40" />

      <div className="relative z-10 p-8 lg:p-10">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <LiveIndicator />
            <span className="text-xs font-mono text-muted">{workflow.workflowId}</span>
            <span className="badge-running text-[10px]">{workflow.status.replace(/_/g, ' ')}</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Clock className="w-3.5 h-3.5" />
            <span className="font-mono">{elapsed}</span>
            <span className="text-border mx-2">|</span>
            <span>ETA {eta}</span>
          </div>
        </div>

        {/* Feature headline */}
        <div className="mb-6">
          <p className="text-xs text-muted font-medium tracking-wider uppercase mb-1.5">
            {workflow.ticketId} &middot; {workflow.issueType || 'Story'} &middot; {workflow.priority || 'Normal'}
          </p>
          <h1 className="text-2xl lg:text-3xl font-bold text-foreground leading-tight mb-3">
            {workflow.summary || 'Workflow in progress'}
          </h1>
          {workflow.currentAgent && (
            <motion.div
              className="inline-flex items-center gap-3 px-4 py-2.5 rounded-xl bg-primary/5 border border-primary/20"
              animate={{
                boxShadow: [
                  '0 0 8px rgba(59,130,246,0.1)',
                  '0 0 20px rgba(59,130,246,0.25)',
                  '0 0 8px rgba(59,130,246,0.1)',
                ],
              }}
              transition={{ duration: 2.5, repeat: Infinity }}
            >
              <Brain className="w-5 h-5 text-primary-light" />
              <div>
                <p className="text-[10px] text-muted uppercase tracking-wider">Current Agent</p>
                <p className="text-sm font-semibold text-primary-light">{currentAgent}</p>
              </div>
            </motion.div>
          )}
        </div>

        {/* Progress bar */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-muted font-medium">Overall Progress</span>
            <span className="text-[11px] text-primary-light font-bold font-mono">{workflow.progress}%</span>
          </div>
          <div className="w-full h-2.5 bg-border/60 rounded-full overflow-hidden">
            <motion.div
              className="h-full rounded-full gradient-primary"
              initial={{ width: 0 }}
              animate={{ width: `${workflow.progress}%` }}
              transition={{ duration: 1.5, ease: 'easeOut' }}
            />
          </div>
        </div>

        {/* Merged Pipeline */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {workflow.stages.map((stage, i) => (
            <PipelineCard key={stage.id} stage={stage} index={i} />
          ))}
        </div>

        {/* AI Confidence */}
        <ConfidenceCard confidence={confidence} />
      </div>
    </motion.section>
  )
}

/* --- Pipeline Card --- */

function PipelineCard({ stage, index }: { stage: WorkflowStage; index: number }) {
  const isRunning = stage.status === 'running'
  const isCompleted = stage.status === 'completed'
  const isFailed = stage.status === 'failed'

  const borderClass = isRunning
    ? 'border-primary/40 shadow-glow-sm'
    : isCompleted
      ? 'border-success/30'
      : isFailed
        ? 'border-error/30'
        : 'border-border/60'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 * index }}
      className={`relative rounded-xl border bg-background/40 backdrop-blur-sm p-4 ${borderClass} ${
        isRunning ? 'animate-glow' : ''
      }`}
    >
      {isCompleted && <div className="absolute top-0 left-2 right-2 h-[2px] rounded-full gradient-success" />}
      {isRunning && <div className="absolute top-0 left-2 right-2 h-[2px] rounded-full gradient-primary" />}

      <div className="flex items-center justify-between mb-2">
        <span className={`p-1.5 rounded-lg ${
          isRunning ? 'bg-primary/10 text-primary-light' :
          isCompleted ? 'bg-success/10 text-success' :
          isFailed ? 'bg-error/10 text-error' :
          'bg-border/50 text-muted/50'
        }`}>
          {stageIcons[stage.id] || <Circle className="w-5 h-5" />}
        </span>
        {isCompleted && <CheckCircle className="w-3.5 h-3.5 text-success" />}
        {isRunning && <Loader className="w-3.5 h-3.5 text-primary-light animate-spin" />}
      </div>

      <p className={`text-xs font-semibold mb-0.5 ${
        isRunning || isCompleted ? 'text-foreground' : isFailed ? 'text-error' : 'text-muted/60'
      }`}>
        {stage.label}
      </p>

      {stage.duration && <p className="text-[10px] text-muted font-mono">{stage.duration}</p>}
      {isRunning && !stage.duration && <p className="text-[10px] text-primary-light">In progress...</p>}
      {isFailed && <p className="text-[10px] text-error">Failed</p>}
      {!isRunning && !isCompleted && !isFailed && !stage.duration && <p className="text-[10px] text-muted/40">Pending</p>}
    </motion.div>
  )
}

/* --- AI Confidence Card (data-driven) --- */

function ConfidenceCard({ confidence }: { confidence: number }) {
  const pct = confidence / 100
  const level = confidence >= 80 ? 'HIGH' : confidence >= 50 ? 'MEDIUM' : confidence > 0 ? 'LOW' : ''
  const badgeClass = confidence >= 80 ? 'badge-completed' : confidence >= 50 ? 'badge-running' : 'badge-pending'

  const reasons = getConfidenceReasons(confidence)

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, delay: 0.6 }}
      className="mt-6 flex items-start gap-6 rounded-xl border border-border bg-background/40 backdrop-blur-sm p-5"
    >
      {/* Circular gauge */}
      <div className="flex-shrink-0 relative w-16 h-16">
        <svg className="w-16 h-16 -rotate-90" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="28" fill="none" stroke="currentColor" strokeWidth="4" className="text-border/40" />
          <motion.circle
            cx="32" cy="32" r="28" fill="none" strokeWidth="4"
            stroke="url(#confidence-gradient)"
            strokeLinecap="round"
            strokeDasharray={176}
            initial={{ strokeDashoffset: 176 }}
            animate={{ strokeDashoffset: 176 * (1 - pct) }}
            transition={{ duration: 1.5, delay: 0.8, ease: 'easeOut' }}
          />
          <defs>
            <linearGradient id="confidence-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10B981" />
              <stop offset="100%" stopColor="#34D399" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-bold text-success">
            {confidence > 0 ? `${confidence}%` : '—'}
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp className="w-4 h-4 text-success" />
          <span className="text-xs font-semibold text-foreground">AI Confidence</span>
          {level ? (
            <span className={`${badgeClass} text-[9px]`}>{level}</span>
          ) : (
            <span className="badge-pending text-[9px]">Calculating...</span>
          )}
        </div>
        <div className="space-y-1">
          {reasons.map((r, i) => (
            <ConfidenceReason key={i} text={r} />
          ))}
        </div>
      </div>
    </motion.div>
  )
}

function getConfidenceReasons(confidence: number): string[] {
  const reasons: string[] = []
  if (confidence >= 20) reasons.push('Planning stage completed successfully')
  if (confidence >= 50) reasons.push('Code generated and committed')
  if (confidence >= 80) reasons.push('Validation checks passing')
  if (confidence >= 100) reasons.push('Release completed — all gates passed')
  if (reasons.length === 0) reasons.push('Analyzing workflow...')
  return reasons
}

function ConfidenceReason({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2">
      <CheckCircle className="w-3 h-3 text-success/70 flex-shrink-0" />
      <span className="text-[11px] text-muted-light">{text}</span>
    </div>
  )
}

/* --- Live Indicator --- */

function LiveIndicator() {
  return (
    <div className="flex items-center gap-2">
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-primary" />
      </span>
      <span className="text-[11px] font-semibold text-primary-light tracking-wider uppercase">Live</span>
    </div>
  )
}

/* --- Helpers --- */

function getElapsed(startedAt: string): string {
  try {
    const ms = Date.now() - new Date(startedAt).getTime()
    const s = Math.floor(ms / 1000)
    const m = Math.floor(s / 60)
    const h = Math.floor(m / 60)
    if (h > 0) return `${h}h ${m % 60}m`
    if (m > 0) return `${m}m ${s % 60}s`
    return `${s}s`
  } catch {
    return '—'
  }
}

function estimateEta(progress: number): string {
  if (progress >= 100) return 'Complete'
  if (progress >= 80) return '~30s'
  if (progress >= 50) return '~1m'
  if (progress >= 20) return '~2m'
  return '~3m'
}
