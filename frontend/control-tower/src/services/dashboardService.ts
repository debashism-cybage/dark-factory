/**
 * Dashboard API service.
 * Fetches live workflow data from the backend.
 */

import { DASHBOARD_ENDPOINT, ARCHITECTURE_TRIGGER_ENDPOINT } from '../config'

export interface DashboardResponse {
  hero: any
  pipeline: any[]
  executiveSummary: any
  quality: any
  activity: any[]
  history: any[]
  architecture?: {
    lastUpdated: string | null
  }
  metadata: {
    generatedAt: string
    dashboardVersion: string
    apiVersion: string
  }
}

export interface TriggerArchitectureResponse {
  message: string
  status: string
}

/**
 * Fetch the dashboard data from the live API.
 * Throws on network failure or non-200 response.
 */
export async function getDashboard(): Promise<DashboardResponse> {
  const response = await fetch(DASHBOARD_ENDPOINT)

  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`)
  }

  return response.json()
}

/**
 * Trigger an on-demand regeneration of the architecture knowledge base.
 * Returns as soon as the agent run has been accepted (fire-and-forget) --
 * the agent itself may take several minutes to finish. Poll getDashboard()
 * for the updated architecture.lastUpdated timestamp.
 * Throws on network failure or non-2xx response.
 */
export async function triggerArchitectureAgent(): Promise<TriggerArchitectureResponse> {
  const response = await fetch(ARCHITECTURE_TRIGGER_ENDPOINT, { method: 'POST' })

  if (!response.ok) {
    throw new Error(`Architecture trigger API returned ${response.status}`)
  }

  return response.json()
}
