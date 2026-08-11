import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, GitBranch, GitPullRequest, FileCode, Calendar, Flag } from 'lucide-react'
import type { WorkflowEvent } from '../types'

interface Props {
  workflow: WorkflowEvent
}

export function WorkflowDetails({ workflow }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.45 }}
      className="card p-6"
    >
      <p className="section-title mb-4">Workflow Details</p>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
        <InfoItem label="Workflow" value={workflow.workflowId} mono />
        <InfoItem label="Ticket" value={workflow.ticketId} />
        <InfoItem label="Priority" value={workflow.priority} icon={<Flag className="w-3 h-3" />} />
        <InfoItem label="Started" value={formatTime(workflow.startedAt)} icon={<Calendar className="w-3 h-3" />} />
        <InfoItem label="Current Phase" value={workflow.currentAgent || '—'} />
        <InfoItem label="Goal" value={workflow.summary} />
      </div>

      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs text-muted hover:text-foreground transition-colors py-2"
      >
        <ChevronDown className={`w-3.5 h-3.5 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
        Technical Details
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-3 border-t border-border/50 space-y-2.5">
              {workflow.artifacts.branch && (
                <TechRow icon={<GitBranch className="w-3.5 h-3.5" />} label="Branch" value={workflow.artifacts.branch} />
              )}
              {workflow.artifacts.pullRequest && (
                <TechRow
                  icon={<GitPullRequest className="w-3.5 h-3.5" />}
                  label="PR"
                  value={`#${workflow.artifacts.pullRequestNumber}`}
                  link={workflow.artifacts.pullRequest}
                />
              )}
              {workflow.artifacts.generatedFiles && (
                <TechRow icon={<FileCode className="w-3.5 h-3.5" />} label="Files" value={`${workflow.artifacts.generatedFiles.length} generated`} />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  )
}

function InfoItem({ label, value, mono, icon }: { label: string; value: string; mono?: boolean; icon?: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] text-muted uppercase tracking-wider mb-0.5">{label}</p>
      <div className="flex items-center gap-1.5">
        {icon && <span className="text-muted">{icon}</span>}
        <p className={`text-sm text-foreground ${mono ? 'font-mono text-xs' : ''} truncate`}>{value || '—'}</p>
      </div>
    </div>
  )
}

function TechRow({ icon, label, value, link }: { icon: React.ReactNode; label: string; value: string; link?: string }) {
  return (
    <div className="flex items-center gap-3 text-xs py-1">
      <span className="text-muted">{icon}</span>
      <span className="text-muted w-20">{label}</span>
      {link ? (
        <a href={link} target="_blank" rel="noopener noreferrer" className="text-primary-light hover:underline font-mono">{value}</a>
      ) : (
        <span className="text-foreground font-mono">{value}</span>
      )}
    </div>
  )
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}
