/**
 * Dashboard API service.
 * Fetches live workflow data from the backend.
 */

import { DASHBOARD_ENDPOINT } from '../config'

export interface DashboardResponse {
  hero: any
  pipeline: any[]
  executiveSummary: any
  quality: any
  activity: any[]
  history: any[]
  metadata: {
    generatedAt: string
    dashboardVersion: string
    apiVersion: string
  }
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
