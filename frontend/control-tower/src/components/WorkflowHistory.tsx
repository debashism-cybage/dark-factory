import { motion } from 'framer-motion'
import { CheckCircle, Clock, XCircle } from 'lucide-react'
import type { WorkflowHistoryItem } from '../types'

interface Props {
  history: WorkflowHistoryItem[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

export function WorkflowHistory({ history, selectedId, onSelect }: Props) {
  if (history.length === 0) return null

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.55 }}
    >
      <p className="section-title mb-4">Recent Workflows</p>
      <div className="space-y-2">
        {history.map((item, i) => (
          <motion.div
            key={item.workflowId}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.05 }}
            onClick={() => onSelect(selectedId === item.workflowId ? null : item.workflowId)}
            className={`card-hover flex items-center gap-4 p-4 cursor-pointer ${
              selectedId === item.workflowId ? '!border-primary/30 !shadow-glow-sm' : ''
            }`}
          >
            <StatusIcon status={item.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-xs font-semibold text-foreground">{item.ticketId}</span>
                <span className="text-[10px] font-mono text-muted">{item.workflowId}</span>
              </div>
              <p className="text-xs text-muted truncate">{item.summary}</p>
            </div>
            <div className="text-right flex-shrink-0">
              <StatusBadge status={item.status} />
              <p className="text-[10px] text-muted font-mono mt-1">{item.duration}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </motion.section>
  )
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'COMPLETED') return <CheckCircle className="w-5 h-5 text-success flex-shrink-0" />
  if (status === 'FAILED') return <XCircle className="w-5 h-5 text-error flex-shrink-0" />
  return <Clock className="w-5 h-5 text-primary-light flex-shrink-0" />
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === 'COMPLETED'
    ? 'badge-completed'
    : status === 'FAILED'
      ? 'badge-failed'
      : 'badge-running'
  return <span className={cls}>{status}</span>
}
