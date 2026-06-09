<template>
  <div class="sub2api-db-page embedded-render">
      <section class="sub2api-db-head">
        <div>
          <h2>Sub2API 数据库</h2>
          <p>连接状态与账号 Priority 同步</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" type="primary" @click="refreshAll">
          刷新
        </el-button>
      </section>

    <section class="database-command-strip">
      <article v-for="item in databaseSummaryCards" :key="item.key" :class="['database-command-card', item.tone]">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <em>{{ item.detail }}</em>
      </article>
    </section>

    <section class="database-status-grid">
      <article class="database-status-panel">
        <div class="database-panel-title">
          <div>
            <span>连接状态</span>
            <strong>{{ statusLabel }}</strong>
          </div>
          <el-tag :type="statusTagType" effect="light">{{ statusLabel }}</el-tag>
        </div>

        <div class="database-kv-grid">
          <div>
            <span>配置</span>
            <strong>{{ status?.config.configured ? '已配置' : '未配置' }}</strong>
          </div>
          <div>
            <span>主机</span>
            <strong>{{ status?.config.host ?? '-' }}</strong>
          </div>
          <div>
            <span>端口</span>
            <strong>{{ status?.config.port ?? '-' }}</strong>
          </div>
          <div>
            <span>用户</span>
            <strong>{{ status?.config.user || '-' }}</strong>
          </div>
          <div>
            <span>库名</span>
            <strong>{{ status?.config.dbname || '-' }}</strong>
          </div>
          <div>
            <span>SSL</span>
            <strong>{{ status?.config.sslmode || '-' }}</strong>
          </div>
        </div>

        <div class="database-dsn">
          <span>DSN</span>
          <code>{{ status?.config.dsn ?? '-' }}</code>
        </div>
      </article>

      <article class="database-status-panel">
        <div class="database-panel-title">
          <div>
            <span>探测结果</span>
            <strong>{{ probeTitle }}</strong>
          </div>
          <el-button :icon="Refresh" :loading="statusLoading" size="small" @click="loadStatus">
            重新探测
          </el-button>
        </div>

        <div class="database-kv-grid compact">
          <div>
            <span>当前库</span>
            <strong>{{ status?.probe?.current_database ?? '-' }}</strong>
          </div>
          <div>
            <span>当前用户</span>
            <strong>{{ status?.probe?.current_user ?? '-' }}</strong>
          </div>
          <div>
            <span>超时</span>
            <strong>{{ status?.config.connect_timeout_seconds ?? '-' }}s</strong>
          </div>
          <div>
            <span>密码</span>
            <strong>{{ status?.config.has_password ? '已配置' : '未配置' }}</strong>
          </div>
        </div>

        <div v-if="status?.probe?.server_version" class="database-dsn">
          <span>版本</span>
          <code>{{ status.probe.server_version }}</code>
        </div>
        <div v-if="status?.probe?.error" class="database-error">
          {{ status.probe.error }}
        </div>
      </article>
    </section>

    <section class="priority-sync-panel">
      <div class="priority-sync-toolbar">
        <div>
          <h3>账号 Priority 同步</h3>
          <p>按平台 base_url 和密钥实际分组倍率排序，写入 sub2api.accounts.priority</p>
        </div>
        <div class="priority-sync-actions">
          <el-button :icon="Refresh" :loading="prioritySyncLoading" size="small" @click="loadPrioritySyncRun">
            刷新结果
          </el-button>
          <el-button
            :icon="Refresh"
            :loading="prioritySyncRunning"
            size="small"
            type="primary"
            @click="runPrioritySync"
          >
            立即同步
          </el-button>
        </div>
      </div>

      <div class="priority-sync-body">
        <div class="priority-sync-run-summary">
          <div>
            <span>最近状态</span>
            <strong>{{ prioritySyncRun ? prioritySyncStatusText(prioritySyncRun.status) : '-' }}</strong>
          </div>
          <div>
            <span>计划项</span>
            <strong>{{ prioritySyncRun?.total_items ?? '-' }}</strong>
          </div>
          <div>
            <span>匹配账号</span>
            <strong>{{ prioritySyncRun?.matched_accounts ?? '-' }}</strong>
          </div>
          <div>
            <span>更新账号</span>
            <strong>{{ prioritySyncRun?.updated_accounts ?? '-' }}</strong>
          </div>
          <div>
            <span>执行人</span>
            <strong>{{ prioritySyncRun?.executed_by_username || '系统' }}</strong>
          </div>
          <div>
            <span>完成时间</span>
            <strong>{{ formatTime(prioritySyncRun?.completed_at ?? null) }}</strong>
          </div>
        </div>

        <div v-if="prioritySyncRun?.error_message" class="database-error">
          {{ prioritySyncRun.error_message }}
        </div>

        <div class="database-table-scroll priority-sync-table-scroll">
          <el-table
            v-loading="prioritySyncLoading || prioritySyncRunning"
            :data="prioritySyncRun?.items ?? []"
            class="priority-sync-table"
            :row-key="prioritySyncRowKey"
          >
            <el-table-column type="expand" width="42">
              <template #default="{ row }">
                <div class="priority-sync-detail">
                  <div class="priority-sync-detail-head">
                    <div class="priority-sync-reason">
                      <span>变更原因</span>
                      <strong>{{ row.change_reason || row.error_message || '-' }}</strong>
                    </div>
                    <div class="priority-sync-metrics">
                      <div>
                        <span>账号 ID 来源</span>
                        <strong>{{ accountLookupSourceLabel(row.account_lookup_source) }}</strong>
                      </div>
                      <div>
                        <span>成功 / 失败</span>
                        <strong>{{ row.updated_account_ids.length }} / {{ row.failed_account_ids.length }}</strong>
                      </div>
                      <div>
                        <span>Admin API</span>
                        <strong>{{ adminApiLabel(row) }}</strong>
                      </div>
                    </div>
                  </div>

                  <div class="priority-sync-account-list">
                    <div class="priority-sync-section-title">
                      <span>匹配账号</span>
                      <strong>{{ row.matched_accounts ?? 0 }} 个匹配，{{ row.updated_accounts ?? 0 }} 个更新</strong>
                    </div>
                    <div v-if="row.matched_account_items.length" class="priority-sync-account-table">
                      <div class="priority-sync-account-row account-head">
                        <span>ID</span>
                        <span>名称</span>
                        <span>原 Priority</span>
                        <span>调度</span>
                        <span>状态</span>
                      </div>
                      <div
                        v-for="account in row.matched_account_items"
                        :key="String(account.id)"
                        class="priority-sync-account-row"
                      >
                        <strong>#{{ account.id ?? '-' }}</strong>
                        <span>{{ accountName(account) }}</span>
                        <span>{{ account.priority_before ?? '-' }}</span>
                        <span>{{ schedulableLabel(account.schedulable) }}</span>
                        <span>{{ account.status ?? '-' }}</span>
                      </div>
                    </div>
                    <strong v-else class="priority-sync-empty">-</strong>
                  </div>

                  <div class="priority-sync-id-strip">
                    <div>
                      <span>成功账号</span>
                      <strong>{{ accountIdList(row.updated_account_ids) }}</strong>
                    </div>
                    <div>
                      <span>失败账号</span>
                      <strong>{{ accountIdList(row.failed_account_ids) }}</strong>
                    </div>
                  </div>

                  <div class="priority-sync-code-grid">
                    <div>
                      <span>请求 Payload</span>
                      <pre>{{ formatJson(row.admin_api_payload) }}</pre>
                    </div>
                    <div>
                      <span>响应</span>
                      <pre>{{ formatJson(row.admin_api_response) }}</pre>
                    </div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-tag :type="prioritySyncStatusTag(row.status)" effect="light" size="small">
                  {{ prioritySyncStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Priority" width="92">
              <template #default="{ row }">
                {{ row.priority ?? '-' }}
              </template>
            </el-table-column>
            <el-table-column label="平台 / base_url" min-width="260">
              <template #default="{ row }">
                <div class="priority-sync-main">
                  <strong>{{ row.platform_name }}</strong>
                  <code>{{ row.normalized_base_url || row.base_url || '-' }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="最低有效倍率" width="180">
              <template #default="{ row }">
                <div class="priority-sync-rate">
                  <strong>{{ formatMultiplier(row.effective_rate_multiplier) }}</strong>
                  <span>{{ selectedGroupLabel(row) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="候选分组" min-width="260">
              <template #default="{ row }">
                <div class="priority-sync-groups">
                  <el-tag
                    v-for="group in row.candidate_groups"
                    :key="group.external_group_id"
                    effect="plain"
                    size="small"
                    type="info"
                  >
                    {{ group.name }}: {{ formatMultiplier(group.effective_rate_multiplier) }}
                  </el-tag>
                  <span v-if="row.candidate_groups.length === 0" class="priority-sync-empty">-</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="账号" width="118">
              <template #default="{ row }">
                {{ row.matched_accounts ?? '-' }} / {{ row.updated_accounts ?? '-' }}
              </template>
            </el-table-column>
            <el-table-column label="错误" min-width="160">
              <template #default="{ row }">
                <span class="priority-sync-error-cell">{{ row.error_message || '-' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  fetchLatestSub2APIPrioritySyncRun,
  fetchSub2APIDatabaseStatus,
  runSub2APIPrioritySync,
  type Sub2APIPrioritySyncItem,
  type Sub2APIPrioritySyncRun,
  type Sub2APIDatabaseStatus,
} from '@/api/client'

const status = ref<Sub2APIDatabaseStatus | null>(null)
const prioritySyncRun = ref<Sub2APIPrioritySyncRun | null>(null)
const loading = ref(false)
const statusLoading = ref(false)
const prioritySyncLoading = ref(false)
const prioritySyncRunning = ref(false)

const statusLabel = computed(() => {
  if (!status.value?.config.configured) {
    return '未配置'
  }
  if (!status.value.probe) {
    return '未探测'
  }
  return status.value.probe.ok ? '连接正常' : '连接失败'
})

const statusTagType = computed(() => {
  if (!status.value?.config.configured) {
    return 'info'
  }
  if (!status.value.probe) {
    return 'warning'
  }
  return status.value.probe.ok ? 'success' : 'danger'
})

const probeTitle = computed(() => {
  if (!status.value?.probe) {
    return '未探测'
  }
  return status.value.probe.ok ? '只读探测通过' : '只读探测失败'
})
const prioritySyncFailedAccounts = computed(() => {
  return prioritySyncRun.value?.items.reduce((sum, item) => sum + item.failed_account_ids.length, 0) ?? 0
})
const prioritySyncSuccessRate = computed(() => {
  const run = prioritySyncRun.value
  if (!run || !run.matched_accounts) {
    return '-'
  }
  return `${Math.round(((run.updated_accounts ?? 0) / run.matched_accounts) * 100)}%`
})
const databaseSummaryCards = computed(() => [
  {
    key: 'connection',
    label: '连接状态',
    value: statusLabel.value,
    detail: status.value?.config.configured ? `${status.value.config.host ?? '-'}:${status.value.config.port ?? '-'}` : '请先配置数据库',
    tone: statusTagType.value === 'success' ? 'ok' : statusTagType.value === 'danger' ? 'bad' : 'warn',
  },
  {
    key: 'sync',
    label: '最近同步',
    value: prioritySyncRun.value ? prioritySyncStatusText(prioritySyncRun.value.status) : '-',
    detail: formatTime(prioritySyncRun.value?.completed_at ?? null),
    tone: prioritySyncRun.value?.status === 'succeeded' ? 'ok' : prioritySyncRun.value?.status === 'failed' ? 'bad' : 'warn',
  },
  {
    key: 'match',
    label: '匹配 / 更新',
    value: `${prioritySyncRun.value?.matched_accounts ?? '-'} / ${prioritySyncRun.value?.updated_accounts ?? '-'}`,
    detail: `成功率 ${prioritySyncSuccessRate.value}`,
    tone: prioritySyncRun.value?.status === 'partial' ? 'warn' : 'neutral',
  },
  {
    key: 'failed',
    label: '失败账号',
    value: String(prioritySyncFailedAccounts.value),
    detail: `计划项 ${prioritySyncRun.value?.total_items ?? '-'}`,
    tone: prioritySyncFailedAccounts.value > 0 ? 'bad' : 'ok',
  },
])

async function loadStatus() {
  statusLoading.value = true
  try {
    status.value = await fetchSub2APIDatabaseStatus(true)
  } catch {
    ElMessage.error('数据库状态加载失败')
  } finally {
    statusLoading.value = false
  }
}

async function loadPrioritySyncRun() {
  prioritySyncLoading.value = true
  try {
    prioritySyncRun.value = await fetchLatestSub2APIPrioritySyncRun()
  } catch {
    ElMessage.error('Priority 同步结果加载失败')
  } finally {
    prioritySyncLoading.value = false
  }
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([loadStatus(), loadPrioritySyncRun()])
  } finally {
    loading.value = false
  }
}

async function runPrioritySync() {
  prioritySyncRunning.value = true
  try {
    prioritySyncRun.value = await runSub2APIPrioritySync()
    ElMessage.success('Priority 同步完成')
  } catch {
    ElMessage.error('Priority 同步失败')
  } finally {
    prioritySyncRunning.value = false
  }
}

function prioritySyncStatusText(statusValue: string) {
  return {
    pending: '执行中',
    planned: '计划',
    succeeded: '成功',
    failed: '失败',
    partial: '部分成功',
    skipped: '跳过',
  }[statusValue] ?? statusValue
}

function prioritySyncStatusTag(statusValue: string) {
  return {
    pending: 'warning',
    planned: 'info',
    succeeded: 'success',
    failed: 'danger',
    partial: 'warning',
    skipped: 'info',
  }[statusValue] ?? 'info'
}

function selectedGroupLabel(row: Sub2APIPrioritySyncItem) {
  if (!row.selected_group) {
    return '-'
  }
  return `${row.selected_group.name} / ${formatMultiplier(row.selected_group.rate_multiplier)}`
}

function prioritySyncRowKey(row: Sub2APIPrioritySyncItem) {
  return `${row.platform_id}:${row.normalized_base_url}:${row.status}`
}

function adminApiLabel(row: Sub2APIPrioritySyncItem) {
  if (!row.admin_api_method && !row.admin_api_path) {
    return '-'
  }
  return `${row.admin_api_method || ''} ${row.admin_api_path || ''}`.trim()
}

function accountLookupSourceLabel(source: string | null) {
  return {
    database: 'Sub2API PostgreSQL',
    admin_api_list_fallback: 'Admin API 列表回退',
  }[source || ''] ?? source ?? '-'
}

function accountIdList(value: number[]) {
  return value.length ? value.join(', ') : '-'
}

function accountName(account: Record<string, unknown>) {
  return account.name ? String(account.name) : '-'
}

function schedulableLabel(value: unknown) {
  if (value === true) {
    return '可调度'
  }
  if (value === false) {
    return '不可调度'
  }
  return '-'
}

function formatJson(value: Record<string, unknown> | null) {
  if (!value) {
    return '-'
  }
  return JSON.stringify(value, null, 2)
}

function formatMultiplier(value: number | null) {
  if (value === null) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatTime(value: string | null) {
  if (!value) {
    return '-'
  }
  const date = parseApiTime(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
  })
}

function parseApiTime(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(normalized)
}

onMounted(refreshAll)
</script>
