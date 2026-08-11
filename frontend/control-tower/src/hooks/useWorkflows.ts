import { useState, useEffect, useRef, useCallback } from 'react'
import type { WorkflowEvent, WorkflowStage, WorkflowHistoryItem } from '../types'
import type { AgentReasoning } from '../components/AIThinkingPanel'
import type { AIDecision } from '../components/AIDecisions'
import { getDashboard } from '../services/dashboardService'
import { POLL_INTERVAL_MS } from '../config'

interface UseWorkflowsResult {
  activeWorkflow: WorkflowEvent | null
  history: WorkflowHistoryItem[]
  reasoning: AgentReasoning[]
  decisions: AIDecision[]
  quality: any
  executiveSummary: any
  isLoading: boolean
  isDisconnected: boolean
}

export function useWorkflows(): UseWorkflowsResult {
  const [activeWorkflow, setActiveWorkflow] = useState<WorkflowEvent | null>(null)
  const [history, setHistory] = useState<WorkflowHistoryItem[]>([])
  const [reasoning, setReasoning] = useState<AgentReasoning[]>([])
  const [decisions, setDecisions] = useState<AIDecision[]>([])
  const [quality, setQuality] = useState<any>(null)
  const [executiveSummary, setExecutiveSummary] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isDisconnected, setIsDisconnected] = useState(false)
  const intervalRef = useRef<number | null>(null)

  const fetchDashboard = useCallback(async () => {
    try {
      const data = await getDashboard()

      const workflow = mapHeroToWorkflow(data.hero, data.pipeline)
      const historyItems = mapHistory(data.history)
      const reasoningItems = mapActivityToReasoning(data.activity, data.pipeline)
      const decisionItems = mapDecisions(data.pipeline, data.hero)

      setActiveWorkflow(workflow)
      setHistory(historyItems)
      setReasoning(reasoningItems)
      setDecisions(decisionItems)
      setQuality(data.quality || null)
      setExecutiveSummary(data.executiveSummary || null)
      setIsDisconnected(false)
      setIsLoading(false)
    } catch {
      setIsDisconnected(true)
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
    intervalRef.current = window.setInterval(fetchDashboard, POLL_INTERVAL_MS)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchDashboard])

  return { activeWorkflow, history, reasoning, decisions, quality, executiveSummary, isLoading, isDisconnected }
}

// ---------------------------------------------------------------------------
// Mappers
// ---------------------------------------------------------------------------

function mapHeroToWorkflow(hero: any, pipeline: any[]): WorkflowEvent | null {
  if (!hero || !hero.workflowId) return null

  const stages: WorkflowStage[] = (pipeline || []).map((s: any) => ({
    id: s.id,
    label: s.label,
    status: s.status,
    duration: s.duration || undefined,
  }))

  const progress = hero.progress ?? hero.confidence ?? 0

  // Extend workflow with confidence and eta from API
  const workflow: any = {
    workflowId: hero.workflowId,
    ticketId: hero.ticketId || '',
    summary: hero.summary || '',
    description: hero.description || '',
    priority: hero.priority || '',
    issueType: hero.issueType || '',
    project: '',
    assignee: '',
    status: hero.status || 'RUNNING',
    currentAgent: hero.currentAgent || '',
    startedAt: hero.startedAt || '',
    completedAt: '',
    stages,
    progress,
    artifacts: {},
    // Extra fields from API
    confidence: hero.confidence ?? 0,
    eta: hero.eta || '',
    elapsed: hero.elapsed || '',
    currentStage: hero.currentStage || '',
  }

  return workflow as WorkflowEvent
}

function mapHistory(history: any[]): WorkflowHistoryItem[] {
  if (!history) return []
  return history.map((item: any) => ({
    workflowId: item.workflowId || '',
    ticketId: item.ticketId || '',
    summary: item.summary || '',
    status: item.status || 'RUNNING',
    startedAt: item.startedAt || '',
    completedAt: item.completedAt,
    duration: item.duration || '',
  }))
}

function mapActivityToReasoning(activity: any[], pipeline: any[]): AgentReasoning[] {
  const agentGroups: Record<string, any[]> = {}
  const agentOrder = ['planning', 'development', 'validation', 'release']

  for (const item of activity || []) {
    const agent = item.agent || ''
    if (!agentGroups[agent]) agentGroups[agent] = []
    agentGroups[agent].push(item)
  }

  const personas: Record<string, string> = {
    planning: 'Solution Architect',
    development: 'Senior Software Engineer',
    validation: 'Quality Assurance Engineer',
    release: 'DevOps Engineer',
  }

  const labels: Record<string, string> = {
    planning: 'Planning Agent',
    development: 'Development Agent',
    validation: 'Validation Agent',
    release: 'Release Agent',
  }

  const pipelineStatus: Record<string, string> = {}
  for (const stage of pipeline || []) {
    pipelineStatus[stage.id] = stage.status
  }

  const reasoning: AgentReasoning[] = []

  for (const agent of agentOrder) {
    const messages = agentGroups[agent] || []
    const status = pipelineStatus[agent] || 'pending'

    const agentStatus: 'completed' | 'running' | 'pending' =
      status === 'completed' ? 'completed' :
      status === 'running' ? 'running' : 'pending'

    const steps = messages.slice(0, 6).map((msg: any, idx: number) => ({
      text: msg.message || '',
      status: agentStatus === 'completed' ? 'completed' as const :
              agentStatus === 'running' && idx === 0 ? 'running' as const :
              agentStatus === 'running' && idx > 0 ? 'completed' as const :
              'pending' as const,
    }))

    if (steps.length === 0 && agentStatus !== 'pending') {
      steps.push({
        text: agentStatus === 'running' ? 'Processing...' : 'Completed',
        status: agentStatus === 'running' ? 'running' as const : 'completed' as const,
      })
    }

    reasoning.push({
      agent,
      label: labels[agent] || agent,
      persona: personas[agent] || '',
      status: agentStatus,
      steps,
    })
  }

  return reasoning
}

function mapDecisions(pipeline: any[], hero: any): AIDecision[] {
  const decisions: AIDecision[] = []

  for (const stage of pipeline || []) {
    if (stage.status === 'completed') {
      switch (stage.id) {
        case 'planning':
          decisions.push({
            id: 'plan-1',
            text: `Implementation plan generated for ${hero?.ticketId || 'ticket'}`,
            icon: 'reuse',
            timestamp: 'Just now',
          })
          break
        case 'development':
          decisions.push({
            id: 'dev-1',
            text: 'Source code generated and committed to feature branch',
            icon: 'pr',
            timestamp: 'Just now',
          })
          decisions.push({
            id: 'dev-2',
            text: 'Pull Request created successfully',
            icon: 'pr',
            timestamp: 'Just now',
          })
          break
        case 'validation':
          decisions.push({
            id: 'val-1',
            text: 'Code review passed — no critical issues',
            icon: 'security',
            timestamp: 'Just now',
          })
          break
        case 'release':
          decisions.push({
            id: 'rel-1',
            text: 'Release completed successfully',
            icon: 'reuse',
            timestamp: 'Just now',
          })
          break
      }
    }
  }

  return decisions.slice(0, 5)
}
