import axios from 'axios'

export interface UserInfo {
  id: number
  username: string
}

export interface SessionInfo {
  user: UserInfo
  csrf_token: string
}

export type PlatformStatus = 'unknown' | 'healthy' | 'degraded' | 'down'

export interface ProviderOption {
  value: string
  label: string
  description: string
}

export interface SiteStrategyOption {
  value: string
  label: string
  provider_type: string
  description: string
}

export interface RelayPlatform {
  id: number
  name: string
  base_url: string
  provider_type: string
  site_strategy: string
  auth_header_name: string
  auth_header_prefix: string
  has_api_key: boolean
  balance_cron: string
  rate_cron: string
  recharge_amount: number
  received_amount: number
  effective_rate_factor: number | null
  balance_last_run_at: string | null
  balance_next_run_at: string | null
  rate_last_run_at: string | null
  rate_next_run_at: string | null
  status: PlatformStatus
  enabled: boolean
  key_count: number
  balance: number | null
  quota_used: number | null
  quota_limit: number | null
  latency_ms: number | null
  last_error: string | null
  checked_at: string | null
  created_at: string
  updated_at: string
}

export interface PlatformPayload {
  name: string
  base_url: string
  provider_type: string
  site_strategy: string
  auth_header_name: string
  auth_header_prefix: string
  api_key?: string | null
  balance_cron: string
  rate_cron: string
  recharge_amount: number
  received_amount: number
  enabled: boolean
  key_count: number
  balance: number | null
  quota_used: number | null
  quota_limit: number | null
}

export interface DashboardStats {
  total_platforms: number
  enabled_platforms: number
  healthy_platforms: number
  degraded_platforms: number
  down_platforms: number
  total_keys: number
  account_monitor_count: number
  group_monitor_count: number
  average_latency_ms: number | null
}

export interface AccountMonitor {
  id: number
  platform_id: number
  name: string
  external_account_id: string
  username: string | null
  has_password: boolean
  enabled: boolean
  balance: number | null
  quota_used: number | null
  quota_limit: number | null
  last_error: string | null
  checked_at: string | null
  created_at: string
  updated_at: string
}

export interface GroupMonitor {
  id: number
  platform_id: number
  name: string
  external_group_id: string
  enabled: boolean
  rate_multiplier: number | null
  effective_rate_multiplier: number | null
  rpm_limit: number | null
  last_error: string | null
  checked_at: string | null
  created_at: string
  updated_at: string
}

export interface DiscoveredGroupRate {
  id: number
  platform_id: number
  external_group_id: string
  name: string
  description: string | null
  rate_multiplier: number | null
  effective_rate_multiplier: number | null
  rpm_limit: number | null
  last_error: string | null
  checked_at: string | null
  configured_monitor_id: number | null
  is_configured: boolean
  created_at: string
  updated_at: string
}

export interface PlatformDetail extends RelayPlatform {
  account_monitors: AccountMonitor[]
  group_monitors: GroupMonitor[]
  discovered_group_rates: DiscoveredGroupRate[]
}

export interface AccountMonitorPayload {
  name: string
  external_account_id: string
  username?: string | null
  password?: string | null
  enabled: boolean
}

export interface GroupMonitorPayload {
  name: string
  external_group_id: string
  enabled: boolean
}

export interface MonitorRunResult {
  platform: RelayPlatform
  account_monitors: AccountMonitor[]
  group_monitors: GroupMonitor[]
}

export interface AccountBalanceHistoryPoint {
  at: string
  balance: number | null
  quota_used: number | null
  quota_limit: number | null
}

export interface AccountBalanceHistorySeries {
  account_id: number
  account_name: string
  points: AccountBalanceHistoryPoint[]
}

export interface GroupRateHistoryPoint {
  at: string
  rate_multiplier: number | null
  effective_rate_multiplier: number | null
  rpm_limit: number | null
}

export interface GroupRateHistorySeries {
  group_id: number | null
  external_group_id: string
  group_name: string
  description: string | null
  configured_monitor_id: number | null
  is_configured: boolean
  points: GroupRateHistoryPoint[]
}

export const http = axios.create({
  baseURL: `${import.meta.env.BASE_URL}api`,
  withCredentials: true,
  timeout: 15000,
})

let csrfToken = ''

export function setCsrfToken(token: string) {
  csrfToken = token
}

http.interceptors.request.use((config) => {
  const method = config.method?.toUpperCase()
  if (csrfToken && method && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    config.headers.set('X-CSRF-Token', csrfToken)
  }
  return config
})

export async function login(username: string, password: string) {
  const csrf = await http.get<{ csrf_token: string }>('/auth/csrf')
  setCsrfToken(csrf.data.csrf_token)
  const { data } = await http.post<SessionInfo>('/auth/login', { username, password })
  setCsrfToken(data.csrf_token)
  return data
}

export async function logout() {
  await http.post('/auth/logout')
  setCsrfToken('')
}

export async function fetchMe() {
  const { data } = await http.get<SessionInfo>('/auth/me')
  setCsrfToken(data.csrf_token)
  return data
}

export async function fetchDashboard() {
  const { data } = await http.get<DashboardStats>('/dashboard')
  return data
}

export async function fetchProviders() {
  const { data } = await http.get<ProviderOption[]>('/providers')
  return data
}

export async function fetchSiteStrategies() {
  const { data } = await http.get<SiteStrategyOption[]>('/site-strategies')
  return data
}

export async function fetchPlatforms() {
  const { data } = await http.get<RelayPlatform[]>('/platforms')
  return data
}

export async function fetchPlatform(id: number) {
  const { data } = await http.get<PlatformDetail>(`/platforms/${id}`)
  return data
}

export async function createPlatform(payload: PlatformPayload) {
  const { data } = await http.post<RelayPlatform>('/platforms', payload)
  return data
}

export async function updatePlatform(id: number, payload: Partial<PlatformPayload>) {
  const { data } = await http.patch<RelayPlatform>(`/platforms/${id}`, payload)
  return data
}

export async function deletePlatform(id: number) {
  await http.delete(`/platforms/${id}`)
}

export async function runPlatformMonitor(id: number) {
  const { data } = await http.post<MonitorRunResult>(`/platforms/${id}/monitor/run`)
  return data
}

export async function runPlatformBalanceMonitor(id: number) {
  const { data } = await http.post<MonitorRunResult>(`/platforms/${id}/monitor/balance/run`)
  return data
}

export async function runPlatformRateMonitor(id: number) {
  const { data } = await http.post<MonitorRunResult>(`/platforms/${id}/monitor/rate/run`)
  return data
}

export async function fetchBalanceHistory(id: number) {
  const { data } = await http.get<AccountBalanceHistorySeries[]>(
    `/platforms/${id}/history/balances`,
  )
  return data
}

export async function fetchRateHistory(id: number) {
  const { data } = await http.get<GroupRateHistorySeries[]>(`/platforms/${id}/history/rates`)
  return data
}

export async function createAccountMonitor(platformId: number, payload: AccountMonitorPayload) {
  const { data } = await http.post<AccountMonitor>(`/platforms/${platformId}/accounts`, payload)
  return data
}

export async function deleteAccountMonitor(platformId: number, monitorId: number) {
  await http.delete(`/platforms/${platformId}/accounts/${monitorId}`)
}

export async function createGroupMonitor(platformId: number, payload: GroupMonitorPayload) {
  const { data } = await http.post<GroupMonitor>(`/platforms/${platformId}/groups`, payload)
  return data
}

export async function deleteGroupMonitor(platformId: number, monitorId: number) {
  await http.delete(`/platforms/${platformId}/groups/${monitorId}`)
}
