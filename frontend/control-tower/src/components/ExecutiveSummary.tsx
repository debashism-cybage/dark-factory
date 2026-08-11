import { motion } from 'framer-motion'
import { Target, Activity, AlertTriangle, Brain, ArrowRight, Clock } from 'lucide-react'
import type { WorkflowEvent } from '../types'

interface Props {
  workflow: WorkflowEvent
  executiveSummary?: {
    businessGoal?: string
    currentStatus?: string
    currentAgent?: string
    risk?: string
    nextAction?: string
    eta?: string
  }
}

export function ExecutiveSummary({ workflow, executiveSummary }: Props) {
  // Use API executive summary if available, otherwise derive from workflow
  const businessGoal = executiveSummary?.businessGoal || workflow.summary || '—'
  const currentStatus = executiveSummary?.currentStatus || formatStatus(workflow.status)
  const risk = executiveSummary?.risk || getRiskLevel(workflow)
  const currentAgent = executiveSummary?.currentAgent || getAgentLabel(workflow.currentAgent)
  const nextAction = executiveSummary?.nextAction || getNextAction(workflow)
  const eta = executiveSummary?.eta || estimateEta(workflow.progress)

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2 }}
      className="card p-6 lg:p-8"
    >
      <p className="section-title mb-5">Executive Summary</p>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-6">
        <SummaryItem
          icon={<Target className="w-4 h-4 text-primary-light" />}
          label="Business Goal"
          value={businessGoal}
        />
        <SummaryItem
          icon={<Activity className="w-4 h-4 text-success" />}
          label="Current Status"
          value={currentStatus}
        />
        <SummaryItem
          icon={<AlertTriangle className="w-4 h-4 text-warning" />}
          label="Risk Level"
          value={risk}
          badge={risk === 'Low' ? 'badge-completed' : risk === 'Medium' ? 'badge-running' : 'badge-failed'}
        />
        <SummaryItem
          icon={<Brain className="w-4 h-4 text-accent" />}
          label="Current AI Agent"
          value={currentAgent}
        />
        <SummaryItem
          icon={<ArrowRight className="w-4 h-4 text-primary-light" />}
          label="Next Action"
          value={nextAction}
        />
        <SummaryItem
          icon={<Clock className="w-4 h-4 text-muted" />}
          label="Est. Completion"
          value={eta}
        />
      </div>
    </motion.section>
  )
}

function SummaryItem({ icon, label, value, badge }: {
  icon: React.ReactNode
  label: string
  value: string
  badge?: string
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        {icon}
        <span className="text-[10px] text-muted uppercase tracking-[0.12em] font-medium">{label}</span>
      </div>
      {badge ? (
        <span className={badge}>{value}</span>
      ) : (
        <p className="text-sm font-medium text-foreground leading-snug">{value || '—'}</p>
      )}
    </div>
  )
}

function getAgentLabel(agent: string): string {
  const labels: Record<string, string> = {
    planning: 'Solution Architect',
    development: 'Senior Software Engineer',
    validation: 'Quality Assurance Engineer',
    release: 'DevOps Engineer',
  }
  return labels[agent] || agent || '—'
}

function getNextAction(workflow: WorkflowEvent): string {
  const running = workflow.stages.find(s => s.status === 'running')
  const pending = workflow.stages.find(s => s.status === 'pending')

  if (running?.id === 'validation') return 'Running quality validation'
  if (running?.id === 'development') return 'Generating source code & PR'
  if (running?.id === 'planning') return 'Generating implementation plan'
  if (running?.id === 'release') return 'Generating release notes'
  if (pending?.id === 'release') return 'Proceed to release'
  if (pending?.id === 'validation') return 'Run quality gates'
  if (workflow.status === 'COMPLETED') return 'Workflow complete'
  if (workflow.status === 'FAILED') return 'Review failure and retry'
  return 'Awaiting next stage'
}

function getRiskLevel(workflow: WorkflowEvent): string {
  if (workflow.status === 'FAILED') return 'High'
  if (workflow.progress < 30) return 'Medium'
  return 'Low'
}

function formatStatus(status: string): string {
  if (!status) return '—'
  return status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function estimateEta(progress: number): string {
  if (progress >= 100) return 'Complete'
  if (progress >= 80) return '~30s'
  if (progress >= 50) return '~1m'
  if (progress >= 20) return '~2m'
  return '~3m'
}
