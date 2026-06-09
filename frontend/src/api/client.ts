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
  today_quota_used: number | null
  low_balance_threshold: number | null
  low_balance_notify_count: number
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
  low_balance_threshold: number | null
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
  today_quota_used: number | null
}

export interface AccountKeySummary {
  id: string
  name: string
  group_id: string | null
  group_name: string | null
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
  today_quota_used: number | null
  key_summaries: AccountKeySummary[]
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

export interface DiscoveredChannelRate {
  id: number
  platform_id: number
  external_channel_id: string
  name: string
  description: string | null
  base_url: string | null
  status: string | null
  rate_multiplier: number | null
  model_rates: Record<string, number>
  last_error: string | null
  checked_at: string | null
  created_at: string
  updated_at: string
}

export interface PlatformDetail extends RelayPlatform {
  account_monitors: AccountMonitor[]
  group_monitors: GroupMonitor[]
  discovered_group_rates: DiscoveredGroupRate[]
  discovered_channel_rates: DiscoveredChannelRate[]
}

export interface AccountMonitorPayload {
  name: string
  external_account_id: string
  username?: string | null
  password?: string | null
  enabled: boolean
}

export interface AccountMonitorUpdatePayload {
  name?: string
  external_account_id?: string
  username?: string | null
  password?: string | null
  enabled?: boolean
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
  discovered_channel_rates: DiscoveredChannelRate[]
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

export interface EmbeddedHistoryResponse {
  balances: Record<number, AccountBalanceHistorySeries[]>
  rates: Record<number, GroupRateHistorySeries[]>
}

export interface NotificationSetting {
  enabled: boolean
  smtp_host: string | null
  smtp_port: number
  smtp_username: string | null
  has_smtp_password: boolean
  smtp_use_ssl: boolean
  smtp_use_tls: boolean
  from_email: string | null
  from_name: string | null
  notify_group_rate_changes: boolean
  notify_low_balance: boolean
  last_error: string | null
  last_tested_at: string | null
  updated_at: string
}

export interface NotificationSettingPayload {
  enabled: boolean
  smtp_host: string | null
  smtp_port: number
  smtp_username: string | null
  smtp_password?: string | null
  smtp_use_ssl: boolean
  smtp_use_tls: boolean
  from_email: string | null
  from_name: string | null
  notify_group_rate_changes: boolean
  notify_low_balance: boolean
}

export interface NotificationRecipient {
  id: number
  name: string
  email: string
  enabled: boolean
  last_error: string | null
  last_tested_at: string | null
  created_at: string
  updated_at: string
}

export interface NotificationRecipientPayload {
  name: string
  email: string
  enabled: boolean
}

export interface Sub2APIDatabaseConfig {
  configured: boolean
  host: string
  port: number
  user: string
  dbname: string
  sslmode: string
  has_password: boolean
  dsn: string | null
  connect_timeout_seconds: number
}

export interface Sub2APIDatabaseProbe {
  ok: boolean
  error: string | null
  current_database: string | null
  current_user: string | null
  server_version: string | null
}

export interface Sub2APIDatabaseStatus {
  config: Sub2APIDatabaseConfig
  probe: Sub2APIDatabaseProbe | null
}

export interface Sub2APISQLLog {
  id: number
  operation: string
  target_database: string
  sql_text: string
  sql_params_json: string | null
  status: string
  affected_rows: number | null
  error_message: string | null
  executed_by_user_id: number | null
  executed_by_username: string | null
  created_at: string
}

export interface Sub2APISQLLogPage {
  items: Sub2APISQLLog[]
  total: number
  limit: number
  offset: number
}

export interface Sub2APIPrioritySyncGroupItem {
  external_group_id: string
  name: string
  source: string
  rate_multiplier: number | null
  rate_factor: number | null
  effective_rate_multiplier: number | null
  rpm_limit: number | null
  last_error: string | null
}

export interface Sub2APIPrioritySyncItem {
  platform_id: number
  platform_name: string
  base_url: string
  normalized_base_url: string
  rate_factor: number | null
  candidate_groups: Sub2APIPrioritySyncGroupItem[]
  selected_group: Sub2APIPrioritySyncGroupItem | null
  effective_rate_multiplier: number | null
  priority: number | null
  status: string
  matched_accounts: number | null
  updated_accounts: number | null
  sql_log_id: number | null
  error_message: string | null
  change_reason: string | null
  matched_account_items: Array<Record<string, unknown>>
  updated_account_ids: number[]
  failed_account_ids: number[]
  admin_api_method: string | null
  admin_api_path: string | null
  admin_api_payload: Record<string, unknown> | null
  admin_api_response: Record<string, unknown> | null
}

export interface Sub2APIPrioritySyncRun {
  id: number
  status: string
  target_database: string
  total_items: number
  succeeded_items: number
  failed_items: number
  skipped_items: number
  matched_accounts: number
  updated_accounts: number
  error_message: string | null
  items: Sub2APIPrioritySyncItem[]
  executed_by_user_id: number | null
  executed_by_username: string | null
  created_at: string
  completed_at: string | null
}

export interface Sub2APIPrioritySyncRunPage {
  items: Sub2APIPrioritySyncRun[]
  total: number
  limit: number
  offset: number
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

export async function fetchPlatformDetails() {
  const { data } = await http.get<PlatformDetail[]>('/platforms/details')
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

export async function fetchEmbeddedHistories(platformIds: number[]) {
  const params = new URLSearchParams()
  for (const platformId of platformIds) {
    params.append('platform_ids', platformId.toString())
  }
  const { data } = await http.get<EmbeddedHistoryResponse>('/platforms/history/embedded', { params })
  return data
}

export async function fetchNotificationSetting() {
  const { data } = await http.get<NotificationSetting>('/notification-settings')
  return data
}

export async function updateNotificationSetting(payload: NotificationSettingPayload) {
  const { data } = await http.put<NotificationSetting>('/notification-settings', payload)
  return data
}

export async function fetchNotificationRecipients() {
  const { data } = await http.get<NotificationRecipient[]>('/notification-recipients')
  return data
}

export async function fetchSub2APIDatabaseStatus(test = true) {
  const { data } = await http.get<Sub2APIDatabaseStatus>('/sub2api/database/status', {
    params: { test },
  })
  return data
}

export async function fetchSub2APISQLLogs(params: {
  limit?: number
  offset?: number
  status?: string
  operation?: string
} = {}) {
  const { data } = await http.get<Sub2APISQLLogPage>('/sub2api/sql-logs', { params })
  return data
}

export async function fetchSub2APISQLLog(id: number) {
  const { data } = await http.get<Sub2APISQLLog>(`/sub2api/sql-logs/${id}`)
  return data
}

export async function fetchSub2APIPrioritySyncRuns(params: {
  limit?: number
  offset?: number
} = {}) {
  const { data } = await http.get<Sub2APIPrioritySyncRunPage>('/sub2api/priority-sync/runs', {
    params,
  })
  return data
}

export async function fetchLatestSub2APIPrioritySyncRun() {
  const { data } = await http.get<Sub2APIPrioritySyncRun | null>(
    '/sub2api/priority-sync/runs/latest',
  )
  return data
}

export async function runSub2APIPrioritySync() {
  const { data } = await http.post<Sub2APIPrioritySyncRun>('/sub2api/priority-sync/run', null, {
    timeout: 120000,
  })
  return data
}

export async function createNotificationRecipient(payload: NotificationRecipientPayload) {
  const { data } = await http.post<NotificationRecipient>('/notification-recipients', payload)
  return data
}

export async function updateNotificationRecipient(id: number, payload: Partial<NotificationRecipientPayload>) {
  const { data } = await http.patch<NotificationRecipient>(`/notification-recipients/${id}`, payload)
  return data
}

export async function deleteNotificationRecipient(id: number) {
  await http.delete(`/notification-recipients/${id}`)
}

export async function testNotificationRecipient(id: number) {
  await http.post(`/notification-recipients/${id}/test`)
}

export async function createAccountMonitor(platformId: number, payload: AccountMonitorPayload) {
  const { data } = await http.post<AccountMonitor>(`/platforms/${platformId}/accounts`, payload)
  return data
}

export async function updateAccountMonitor(
  platformId: number,
  monitorId: number,
  payload: AccountMonitorUpdatePayload,
) {
  const { data } = await http.patch<AccountMonitor>(`/platforms/${platformId}/accounts/${monitorId}`, payload)
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
