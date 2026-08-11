export type WorkflowStatus =
  | 'STARTED'
  | 'PLANNED'
  | 'DEVELOPMENT_COMPLETE'
  | 'VALIDATION_COMPLETE'
  | 'COMPLETED'
  | 'FAILED'

export type AgentName =
  | 'planning'
  | 'architecture'
  | 'development'
  | 'validation'
  | 'release'

export type StageStatus = 'completed' | 'running' | 'pending' | 'failed'

export interface WorkflowStage {
  id: AgentName
  label: string
  status: StageStatus
  startedAt?: string
  completedAt?: string
  duration?: string
}

export interface WorkflowEvent {
  workflowId: string
  ticketId: string
  summary: string
  description: string
  priority: string
  issueType: string
  project: string
  assignee: string
  status: WorkflowStatus
  currentAgent: AgentName | ''
  startedAt: string
  completedAt?: string
  stages: WorkflowStage[]
  progress: number
  artifacts: WorkflowArtifacts
}

export interface WorkflowArtifacts {
  branch?: string
  pullRequest?: string
  pullRequestNumber?: number
  commitSha?: string
  generatedFiles?: GeneratedFile[]
  validationReport?: string
  releaseNotes?: string
}

export interface GeneratedFile {
  path: string
  size: number
}

export interface ActivityItem {
  id: string
  timestamp: string
  agent: AgentName
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
}

export interface QualityMetric {
  id: string
  label: string
  value: string
  status: 'passed' | 'failed' | 'running' | 'pending'
  icon: string
}

export interface WorkflowHistoryItem {
  workflowId: string
  ticketId: string
  summary: string
  status: WorkflowStatus
  startedAt: string
  completedAt?: string
  duration: string
}
