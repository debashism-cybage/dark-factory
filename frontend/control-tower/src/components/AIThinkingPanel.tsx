import { motion, AnimatePresence } from 'framer-motion'
import { Brain, Code2, Shield, Rocket, CheckCircle, Loader, User } from 'lucide-react'
import type { AgentName } from '../types'

export interface AgentReasoning {
  agent: AgentName
  label: string
  persona: string
  steps: ReasoningStep[]
  status: 'completed' | 'running' | 'pending'
}

export interface ReasoningStep {
  text: string
  status: 'completed' | 'running' | 'pending'
}

interface Props {
  reasoning: AgentReasoning[]
}

const agentIcons: Record<AgentName, React.ReactNode> = {
  planning: <Brain className="w-5 h-5" />,
  architecture: <Brain className="w-5 h-5" />,
  development: <Code2 className="w-5 h-5" />,
  validation: <Shield className="w-5 h-5" />,
  release: <Rocket className="w-5 h-5" />,
}

const agentColors: Record<AgentName, string> = {
  planning: 'text-accent',
  architecture: 'text-accent',
  development: 'text-primary-light',
  validation: 'text-success',
  release: 'text-warning',
}

export function AIThinkingPanel({ reasoning }: Props) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.3 }}
      className="card p-6 lg:p-8"
    >
      <div className="mb-6">
        <p className="section-title mb-1">Live AI Collaboration</p>
        <p className="text-xs text-muted">Watch the AI workforce collaborate in real time</p>
      </div>

      <div className="space-y-1 max-h-[500px] overflow-y-auto pr-2">
        <AnimatePresence>
          {reasoning.map((agent, i) => (
            <AgentBlock key={agent.agent} agent={agent} index={i} />
          ))}
        </AnimatePresence>
      </div>
    </motion.section>
  )
}

function AgentBlock({ agent, index }: { agent: AgentReasoning; index: number }) {
  const isRunning = agent.status === 'running'
  const isCompleted = agent.status === 'completed'
  const isPending = agent.status === 'pending'

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.35, delay: index * 0.08 }}
      className={`rounded-xl p-5 mb-3 transition-all duration-300 ${
        isRunning
          ? 'bg-primary/[0.04] border border-primary/20 shadow-glow-sm'
          : isCompleted
            ? 'bg-card-hover/80 border border-border'
            : 'bg-card-hover/40 border border-border/40 opacity-60'
      }`}
    >
      {/* Agent header with persona */}
      <div className="flex items-center gap-3 mb-4">
        <div className={`p-2 rounded-xl ${
          isRunning ? 'bg-primary/10' :
          isCompleted ? 'bg-success/10' :
          'bg-border/50'
        }`}>
          <span className={
            isRunning ? 'text-primary-light' :
            isCompleted ? 'text-success' :
            'text-muted/50'
          }>
            {agentIcons[agent.agent]}
          </span>
        </div>
        <div className="flex-1">
          <p className={`text-sm font-semibold ${
            isPending ? 'text-muted/50' : 'text-foreground'
          }`}>
            {agent.label}
          </p>
          <p className={`text-[11px] ${agentColors[agent.agent]} font-medium`}>
            {agent.persona}
          </p>
        </div>
        <AgentStatus status={agent.status} />
      </div>

      {/* Steps */}
      {!isPending && (
        <div className="space-y-2 pl-3 ml-3 border-l border-border/50">
          {agent.steps.map((step, stepIdx) => (
            <StepLine
              key={stepIdx}
              step={step}
              isLastRunning={step.status === 'running' && stepIdx === agent.steps.findIndex(s => s.status === 'running')}
            />
          ))}
        </div>
      )}
    </motion.div>
  )
}

function AgentStatus({ status }: { status: AgentReasoning['status'] }) {
  if (status === 'completed') {
    return <span className="badge-completed text-[9px]">Completed</span>
  }
  if (status === 'running') {
    return (
      <span className="badge-running text-[9px]">
        <Loader className="w-3 h-3 animate-spin" />
        Working
      </span>
    )
  }
  return <span className="badge-pending text-[9px]">Waiting</span>
}

function StepLine({ step, isLastRunning }: { step: ReasoningStep; isLastRunning: boolean }) {
  const isRunning = step.status === 'running'
  const isCompleted = step.status === 'completed'

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-2.5 py-0.5"
    >
      {isCompleted && <CheckCircle className="w-3.5 h-3.5 text-success/70 flex-shrink-0" />}
      {isRunning && <Loader className="w-3.5 h-3.5 text-primary-light animate-spin flex-shrink-0" />}
      {step.status === 'pending' && (
        <span className="w-3.5 h-3.5 flex items-center justify-center flex-shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-muted/30" />
        </span>
      )}
      <span className={`text-xs leading-relaxed ${
        isRunning ? 'text-foreground font-medium' :
        isCompleted ? 'text-muted-light' :
        'text-muted/40'
      }`}>
        {step.text}
        {isRunning && isLastRunning && <TypingCursor />}
      </span>
    </motion.div>
  )
}

function TypingCursor() {
  return <span className="inline-block w-[2px] h-3.5 bg-primary-light ml-1 animate-blink align-middle" />
}
