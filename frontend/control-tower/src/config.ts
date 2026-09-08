/**
 * Application configuration.
 * All environment-specific values are centralized here.
 */

export const API_BASE_URL =
  'https://pqcqdsfue5.execute-api.us-east-1.amazonaws.com'

export const DASHBOARD_ENDPOINT = `${API_BASE_URL}/dashboard`

export const ARCHITECTURE_TRIGGER_ENDPOINT = `${API_BASE_URL}/architecture/trigger`

export const POLL_INTERVAL_MS = 3000
