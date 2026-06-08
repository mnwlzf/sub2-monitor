<template>
  <div class="sub2api-db-page embedded-render">
      <section class="sub2api-db-head">
        <div>
          <h2>Sub2API 数据库</h2>
          <p>连接状态与 SQL 修改日志</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" type="primary" @click="refreshAll">
          刷新
        </el-button>
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

    <section class="sql-log-panel priority-sync-panel">
      <div class="sql-log-toolbar">
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
        <div class="database-kv-grid priority-sync-summary">
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

        <el-table
          v-loading="prioritySyncLoading || prioritySyncRunning"
          :data="prioritySyncRun?.items ?? []"
          class="sql-log-table"
          :row-key="prioritySyncRowKey"
        >
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
          <el-table-column label="最低有效倍率" min-width="170">
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
          <el-table-column label="错误" min-width="180">
            <template #default="{ row }">
              <span class="sql-error-cell">{{ row.error_message || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column align="right" label="SQL" width="86">
            <template #default="{ row }">
              <el-button
                :disabled="!row.sql_log_id"
                link
                type="primary"
                @click="row.sql_log_id && openLog(row.sql_log_id)"
              >
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <section class="sql-log-panel">
      <div class="sql-log-toolbar">
        <div>
          <h3>SQL 修改日志</h3>
          <p>{{ logs.total }} 条记录</p>
        </div>
        <div class="sql-log-filters">
          <el-select
            v-model="filters.status"
            clearable
            placeholder="状态"
            size="small"
            @change="reloadLogsFromFirstPage"
          >
            <el-option label="成功" value="succeeded" />
            <el-option label="失败" value="failed" />
            <el-option label="执行中" value="pending" />
          </el-select>
          <el-input
            v-model.trim="filters.operation"
            clearable
            placeholder="操作"
            size="small"
            @clear="reloadLogsFromFirstPage"
            @keyup.enter="reloadLogsFromFirstPage"
          />
          <el-button :icon="Refresh" :loading="logsLoading" size="small" @click="loadLogs">
            刷新
          </el-button>
        </div>
      </div>

      <el-table v-loading="logsLoading" :data="logs.items" class="sql-log-table" row-key="id">
        <el-table-column label="时间" min-width="170">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <el-tag :type="logStatusTag(row.status)" effect="light" size="small">
              {{ logStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="130" prop="operation" />
        <el-table-column label="执行人" min-width="120">
          <template #default="{ row }">
            {{ row.executed_by_username || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="影响行数" width="100">
          <template #default="{ row }">
            {{ row.affected_rows ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column label="SQL" min-width="280">
          <template #default="{ row }">
            <code class="sql-inline">{{ sqlSummary(row.sql_text) }}</code>
          </template>
        </el-table-column>
        <el-table-column label="错误" min-width="180">
          <template #default="{ row }">
            <span class="sql-error-cell">{{ row.error_message || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column align="right" label="操作" width="96">
          <template #default="{ row }">
            <el-button :icon="View" link type="primary" @click="openLog(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="sql-log-pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[25, 50, 100, 200]"
          :total="logs.total"
          background
          layout="total, sizes, prev, pager, next"
          @current-change="loadLogs"
          @size-change="reloadLogsFromFirstPage"
        />
      </div>
    </section>

    <el-dialog v-model="detailVisible" title="SQL 修改日志" width="760px">
      <div v-if="selectedLog" class="sql-log-detail">
        <div class="sql-log-detail-grid">
          <div>
            <span>状态</span>
            <strong>{{ logStatusText(selectedLog.status) }}</strong>
          </div>
          <div>
            <span>操作</span>
            <strong>{{ selectedLog.operation }}</strong>
          </div>
          <div>
            <span>执行人</span>
            <strong>{{ selectedLog.executed_by_username || '-' }}</strong>
          </div>
          <div>
            <span>影响行数</span>
            <strong>{{ selectedLog.affected_rows ?? '-' }}</strong>
          </div>
          <div>
            <span>目标库</span>
            <strong>{{ selectedLog.target_database }}</strong>
          </div>
          <div>
            <span>时间</span>
            <strong>{{ formatTime(selectedLog.created_at) }}</strong>
          </div>
        </div>

        <div class="sql-log-code-block">
          <span>SQL</span>
          <pre>{{ selectedLog.sql_text }}</pre>
        </div>
        <div v-if="selectedLog.sql_params_json" class="sql-log-code-block">
          <span>参数</span>
          <pre>{{ formattedSelectedParams }}</pre>
        </div>
        <div v-if="selectedLog.error_message" class="database-error detail-error">
          {{ selectedLog.error_message }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { Refresh, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  fetchLatestSub2APIPrioritySyncRun,
  fetchSub2APIDatabaseStatus,
  fetchSub2APISQLLog,
  fetchSub2APISQLLogs,
  runSub2APIPrioritySync,
  type Sub2APIPrioritySyncItem,
  type Sub2APIPrioritySyncRun,
  type Sub2APIDatabaseStatus,
  type Sub2APISQLLog,
  type Sub2APISQLLogPage,
} from '@/api/client'

const status = ref<Sub2APIDatabaseStatus | null>(null)
const prioritySyncRun = ref<Sub2APIPrioritySyncRun | null>(null)
const logs = ref<Sub2APISQLLogPage>({
  items: [],
  total: 0,
  limit: 25,
  offset: 0,
})
const filters = reactive({
  status: '',
  operation: '',
})
const loading = ref(false)
const statusLoading = ref(false)
const prioritySyncLoading = ref(false)
const prioritySyncRunning = ref(false)
const logsLoading = ref(false)
const detailVisible = ref(false)
const selectedLog = ref<Sub2APISQLLog | null>(null)
const currentPage = ref(1)
const pageSize = ref(25)

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

const formattedSelectedParams = computed(() => {
  const rawValue = selectedLog.value?.sql_params_json
  if (!rawValue) {
    return ''
  }
  try {
    return JSON.stringify(JSON.parse(rawValue), null, 2)
  } catch {
    return rawValue
  }
})

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

async function loadLogs() {
  logsLoading.value = true
  try {
    logs.value = await fetchSub2APISQLLogs({
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
      status: filters.status || undefined,
      operation: filters.operation || undefined,
    })
  } catch {
    ElMessage.error('SQL 日志加载失败')
  } finally {
    logsLoading.value = false
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
    await Promise.all([loadStatus(), loadPrioritySyncRun(), loadLogs()])
  } finally {
    loading.value = false
  }
}

async function reloadLogsFromFirstPage() {
  currentPage.value = 1
  await loadLogs()
}

async function openLog(id: number) {
  selectedLog.value = await fetchSub2APISQLLog(id)
  detailVisible.value = true
}

async function runPrioritySync() {
  prioritySyncRunning.value = true
  try {
    prioritySyncRun.value = await runSub2APIPrioritySync()
    await loadLogs()
    ElMessage.success('Priority 同步完成')
  } catch {
    ElMessage.error('Priority 同步失败')
  } finally {
    prioritySyncRunning.value = false
  }
}

function logStatusText(statusValue: string) {
  return {
    pending: '执行中',
    succeeded: '成功',
    failed: '失败',
  }[statusValue] ?? statusValue
}

function logStatusTag(statusValue: string) {
  return {
    pending: 'warning',
    succeeded: 'success',
    failed: 'danger',
  }[statusValue] ?? 'info'
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

function sqlSummary(sql: string) {
  const normalized = sql.replace(/\s+/g, ' ').trim()
  return normalized.length > 140 ? `${normalized.slice(0, 140)}...` : normalized
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
