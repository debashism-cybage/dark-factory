import { motion } from 'framer-motion'
import { Sparkles, CheckCircle, Shield, GitPullRequest, TestTube, Lock } from 'lucide-react'

export interface AIDecision {
  id: string
  text: string
  icon: 'auth' | 'reuse' | 'tests' | 'security' | 'pr'
  timestamp: string
}

interface Props {
  decisions: AIDecision[]
}

const decisionIcons: Record<string, React.ReactNode> = {
  auth: <Lock className="w-3.5 h-3.5" />,
  reuse: <CheckCircle className="w-3.5 h-3.5" />,
  tests: <TestTube className="w-3.5 h-3.5" />,
  security: <Shield className="w-3.5 h-3.5" />,
  pr: <GitPullRequest className="w-3.5 h-3.5" />,
}

export function AIDecisions({ decisions }: Props) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.4 }}
      className="card p-6"
    >
      <div className="flex items-center gap-2 mb-5">
        <Sparkles className="w-4 h-4 text-warning" />
        <p className="section-title">Recent AI Decisions</p>
      </div>

      <div className="space-y-3">
        {decisions.map((decision, i) => (
          <motion.div
            key={decision.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: i * 0.06 }}
            className="flex items-start gap-3 group"
          >
            <span className="mt-0.5 p-1 rounded-md bg-success/10 text-success flex-shrink-0">
              {decisionIcons[decision.icon] || <CheckCircle className="w-3.5 h-3.5" />}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-foreground leading-relaxed">{decision.text}</p>
              <p className="text-[10px] text-muted font-mono mt-0.5">{decision.timestamp}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </motion.section>
  )
}
