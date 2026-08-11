import { motion } from 'framer-motion'
import { Header } from './components/Header'
import { HeroSection } from './components/HeroSection'
import { ExecutiveSummary } from './components/ExecutiveSummary'
import { AIThinkingPanel } from './components/AIThinkingPanel'
import { AIDecisions } from './components/AIDecisions'
import { QualityCards } from './components/QualityCards'
import { WorkflowDetails } from './components/WorkflowDetails'
import { WorkflowHistory } from './components/WorkflowHistory'
import { useWorkflows } from './hooks/useWorkflows'
import { useState } from 'react'
import { WifiOff, Loader } from 'lucide-react'

function App() {
  const {
    activeWorkflow,
    history,
    reasoning,
    decisions,
    quality,
    executiveSummary,
    isLoading,
    isDisconnected,
  } = useWorkflows()
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-background">
      <Header isDisconnected={isDisconnected} />

      <motion.main
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5 }}
        className="max-w-[1400px] mx-auto px-8 py-8 space-y-8"
      >
        {isDisconnected && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-warning/10 border border-warning/20 text-warning text-xs font-medium"
          >
            <WifiOff className="w-3.5 h-3.5" />
            Disconnected — showing last known state
          </motion.div>
        )}

        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="card p-20 text-center"
          >
            <Loader className="w-8 h-8 text-primary-light animate-spin mx-auto mb-4" />
            <p className="text-sm text-muted">Connecting to Dark Factory...</p>
          </motion.div>
        )}

        {!isLoading && activeWorkflow ? (
          <>
            <HeroSection workflow={activeWorkflow} />
            <ExecutiveSummary workflow={activeWorkflow} executiveSummary={executiveSummary} />
            <QualityCards quality={quality} />

            <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
              <div className="lg:col-span-3">
                <AIThinkingPanel reasoning={reasoning} />
              </div>
              <div className="lg:col-span-2 space-y-6">
                <AIDecisions decisions={decisions} />
                <WorkflowDetails workflow={activeWorkflow} />
              </div>
            </div>
          </>
        ) : !isLoading ? (
          <EmptyState />
        ) : null}

        {!isLoading && (
          <WorkflowHistory
            history={history}
            selectedId={selectedWorkflowId}
            onSelect={setSelectedWorkflowId}
          />
        )}
      </motion.main>
    </div>
  )
}

function EmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="card p-20 text-center"
    >
      <div className="text-6xl mb-6">🏭</div>
      <h2 className="text-xl font-semibold text-foreground mb-2">No Active Workflows</h2>
      <p className="text-sm text-muted max-w-md mx-auto">
        Move a Jira ticket to "In Progress" to start the autonomous delivery pipeline
      </p>
    </motion.div>
  )
}

export default App
