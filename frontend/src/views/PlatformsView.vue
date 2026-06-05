<template>
  <div class="platforms-page">
    <section v-if="!isEmbedded" class="page-hero">
      <div>
        <div class="eyebrow">平台监控</div>
        <h2>平台列表</h2>
        <p>按 sub2api / newapi 策略采集账号余额和指定分组倍率。</p>
      </div>
      <div class="hero-meta">
        <div class="hero-chip">
          <span>总平台</span>
          <strong>{{ stats?.total_platforms ?? '-' }}</strong>
        </div>
        <div class="hero-chip">
          <span>异常</span>
          <strong class="bad">{{ (stats?.degraded_platforms ?? 0) + (stats?.down_platforms ?? 0) }}</strong>
        </div>
        <el-button :icon="Plus" type="primary" @click="openCreate">新增平台</el-button>
      </div>
    </section>

    <section v-if="!isEmbedded" class="stats-grid">
      <div class="stat-card">
        <span>平台总数</span>
        <strong>{{ stats?.total_platforms ?? '-' }}</strong>
      </div>
      <div class="stat-card">
        <span>启用平台</span>
        <strong>{{ stats?.enabled_platforms ?? '-' }}</strong>
      </div>
      <div class="stat-card">
        <span>健康</span>
        <strong class="ok">{{ stats?.healthy_platforms ?? '-' }}</strong>
      </div>
      <div class="stat-card">
        <span>异常</span>
        <strong class="bad">{{ (stats?.degraded_platforms ?? 0) + (stats?.down_platforms ?? 0) }}</strong>
      </div>
      <div class="stat-card">
        <span>账号监控</span>
        <strong>{{ stats?.account_monitor_count ?? '-' }}</strong>
      </div>
      <div class="stat-card">
        <span>分组监控</span>
        <strong>{{ stats?.group_monitor_count ?? '-' }}</strong>
      </div>
    </section>

    <section v-if="!isEmbedded" class="table-card">
      <el-table v-loading="loading" :data="platforms" class="platform-table compare-table" row-key="id">
        <el-table-column label="平台" min-width="240">
          <template #default="{ row }">
            <div class="platform-cell">
              <div class="platform-name">{{ row.name }}</div>
              <div class="platform-badges">
                <el-tag size="small" effect="plain">{{ providerLabel(row.provider_type) }}</el-tag>
                <el-tag size="small" effect="light" type="info">{{ siteStrategyLabel(row) }}</el-tag>
              </div>
              <div class="muted">{{ row.base_url }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isEmbedded" label="状态" width="120">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag :type="statusType(row.status)" effect="light">{{ statusText(row.status) }}</el-tag>
              <span class="status-subtext">{{ row.enabled ? '启用中' : '已停用' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!isEmbedded" label="地址" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono-url">{{ row.base_url }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isEmbedded" label="凭据" width="110">
          <template #default="{ row }">
            <div class="credential-cell">
              <el-tag :type="row.has_api_key ? 'success' : 'info'" effect="plain">
                {{ row.has_api_key ? '已配置' : '未配置' }}
              </el-tag>
              <span class="status-subtext">{{ row.has_api_key ? 'API Key' : '待补充' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="账号概览" min-width="320">
          <template #default="{ row }">
            <div class="account-compare-list">
              <div
                v-for="account in row.account_monitors.slice(0, 3)"
                :key="account.id"
                class="account-compare-item"
              >
                <div class="account-compare-name">
                  <span>{{ account.name }}</span>
                  <el-tag
                    :type="account.last_error ? 'danger' : account.checked_at ? 'success' : 'info'"
                    effect="light"
                    size="small"
                  >
                    {{ account.last_error ? '异常' : account.checked_at ? '正常' : '未采集' }}
                  </el-tag>
                </div>
                <div class="account-compare-metrics">
                  <span><em>余额</em> {{ formatMoney(account.balance) }}</span>
                  <span><em>消耗</em> {{ formatMoney(account.quota_used) }}</span>
                </div>
              </div>
              <div v-if="row.account_monitors.length === 0" class="muted">未配置账号</div>
              <div v-else-if="row.account_monitors.length > 3" class="muted">
                还有 {{ row.account_monitors.length - 3 }} 个账号，进入监控项查看
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="指标" width="150">
          <template #default="{ row }">
            <div class="metric-stack">
              <div>
                <span class="metric-label">账号数</span>
                <strong>{{ row.account_monitors.length }}</strong>
              </div>
              <div>
                <span class="metric-label">总余额</span>
                <strong>{{ formatMoney(row.balance) }}</strong>
              </div>
              <div>
                <span class="metric-label">总消耗</span>
                <strong>{{ formatMoney(row.quota_used) }}</strong>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="最后采集" width="170">
          <template #default="{ row }">
            <div class="time-cell">
              <span>{{ formatTime(row.checked_at) }}</span>
              <span class="status-subtext">采集时间</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <div class="switch-cell">
              <el-switch :model-value="row.enabled" @change="toggleEnabled(row)" />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="132" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button :icon="Setting" circle title="监控项" @click="openDetail(row)" />
              <el-button :icon="Refresh" circle title="采集" @click="runMonitor(row)" />
              <el-button :icon="Edit" circle title="编辑" @click="openEdit(row)" />
              <el-button :icon="Delete" circle plain title="删除" type="danger" @click="remove(row)" />
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-else v-loading="loading" class="embedded-workspace">
      <aside class="embedded-menu">
        <div class="embedded-menu-brand">
          <strong>Sub2 Monitor</strong>
          <span>功能菜单</span>
        </div>
        <button
          v-for="item in embeddedMenuItems"
          :key="item.key"
          :class="{ active: activeEmbeddedView === item.key }"
          type="button"
          @click="activeEmbeddedView = item.key"
        >
          <span>{{ item.label }}</span>
          <small>{{ item.description }}</small>
        </button>
      </aside>

      <main class="embedded-render">
        <div class="embedded-render-head">
          <div>
            <h3>{{ embeddedViewTitle }}</h3>
            <p>{{ embeddedViewDescription }}</p>
          </div>
          <el-button :icon="Plus" size="small" type="primary" @click="openCreate">新增平台</el-button>
        </div>

        <div v-if="activeEmbeddedView === 'overview'" class="embedded-panel-list">
          <section class="stats-grid embedded-stats-grid">
            <div class="stat-card">
              <span>平台总数</span>
              <strong>{{ stats?.total_platforms ?? '-' }}</strong>
            </div>
            <div class="stat-card">
              <span>启用平台</span>
              <strong>{{ stats?.enabled_platforms ?? '-' }}</strong>
            </div>
            <div class="stat-card">
              <span>健康</span>
              <strong class="ok">{{ stats?.healthy_platforms ?? '-' }}</strong>
            </div>
            <div class="stat-card">
              <span>异常</span>
              <strong class="bad">{{ (stats?.degraded_platforms ?? 0) + (stats?.down_platforms ?? 0) }}</strong>
            </div>
            <div class="stat-card">
              <span>账号监控</span>
              <strong>{{ stats?.account_monitor_count ?? '-' }}</strong>
            </div>
            <div class="stat-card">
              <span>分组监控</span>
              <strong>{{ stats?.group_monitor_count ?? '-' }}</strong>
            </div>
          </section>

          <article v-for="row in platforms" :key="row.id" class="embedded-platform-card">
            <header class="embedded-platform-header">
              <div class="embedded-platform-title">
                <div>
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.base_url }}</span>
                </div>
                <div class="platform-badges">
                  <el-tag size="small" effect="plain">{{ providerLabel(row.provider_type) }}</el-tag>
                  <el-tag size="small" effect="light" type="info">{{ siteStrategyLabel(row) }}</el-tag>
                  <el-tag :type="statusType(row.status)" effect="light" size="small">
                    {{ statusText(row.status) }}
                  </el-tag>
                </div>
              </div>
              <div class="embedded-platform-controls">
                <el-switch :model-value="row.enabled" @change="toggleEnabled(row)" />
                <div class="table-actions">
                  <el-button :icon="Setting" circle title="监控项" @click="openDetail(row)" />
                  <el-button :icon="Refresh" circle title="采集" @click="runMonitor(row)" />
                  <el-button :icon="Edit" circle title="编辑" @click="openEdit(row)" />
                  <el-button :icon="Delete" circle plain title="删除" type="danger" @click="remove(row)" />
                </div>
              </div>
            </header>

            <div class="embedded-platform-body">
              <div class="embedded-account-panel">
                <div class="embedded-section-label">账号概览</div>
                <div v-if="row.account_monitors.length > 0" class="embedded-account-list">
                  <div
                    v-for="account in row.account_monitors"
                    :key="account.id"
                    class="embedded-account-row"
                  >
                    <div class="embedded-account-main">
                      <div class="embedded-account-name">
                        <strong>{{ account.name }}</strong>
                        <el-tag
                          :type="account.last_error ? 'danger' : account.checked_at ? 'success' : 'info'"
                          effect="light"
                          size="small"
                        >
                          {{ account.last_error ? '异常' : account.checked_at ? '正常' : '未采集' }}
                        </el-tag>
                      </div>
                      <div v-if="account.last_error" class="embedded-account-error">
                        {{ account.last_error }}
                      </div>
                    </div>
                    <div class="embedded-account-values">
                      <div>
                        <span>余额</span>
                        <strong>{{ formatMoney(account.balance) }}</strong>
                      </div>
                      <div>
                        <span>消耗</span>
                        <strong>{{ formatMoney(account.quota_used) }}</strong>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="embedded-empty">未配置账号</div>
              </div>

              <div class="embedded-metrics">
                <div>
                  <span>账号数</span>
                  <strong>{{ row.account_monitors.length }}</strong>
                </div>
                <div>
                  <span>总余额</span>
                  <strong>{{ formatMoney(row.balance) }}</strong>
                </div>
                <div>
                  <span>总消耗</span>
                  <strong>{{ formatMoney(row.quota_used) }}</strong>
                </div>
                <div>
                  <span>最后采集</span>
                  <strong>{{ formatTime(row.checked_at) }}</strong>
                </div>
              </div>
            </div>
          </article>
          <el-empty v-if="!loading && platforms.length === 0" description="暂无平台" />
        </div>

        <div v-else-if="activeEmbeddedView === 'balances'" class="embedded-panel-list">
          <article v-for="row in platforms" :key="row.id" class="embedded-trends-section">
            <div class="embedded-platform-title compact">
              <strong>{{ row.name }}</strong>
              <span>最近 24 小时，每个账号按小时展示余额变化</span>
            </div>
            <div class="embedded-trend-grid">
              <div
                v-for="series in platformBalanceHistory[row.id] ?? []"
                :key="series.account_id"
                class="embedded-trend-card"
              >
                <div class="embedded-trend-head">
                  <span>{{ series.account_name }}</span>
                  <strong>{{ latestBalance(series) }}</strong>
                </div>
                <svg class="embedded-trend-chart" viewBox="0 0 320 96" role="img">
                  <polyline
                    v-if="chartPath(balanceChartValues(series), 56)"
                    :points="chartPath(balanceChartValues(series), 56)"
                    class="trend-line balance-line"
                  />
                  <g v-for="point in chartPoints(balanceChartValues(series), 56)" :key="point.key">
                    <circle :cx="point.x" :cy="point.y" r="2.2" class="trend-dot balance-dot" />
                  </g>
                </svg>
                <div v-if="!hasChartData(balanceChartValues(series))" class="embedded-trend-empty">
                  暂无历史
                </div>
              </div>
            </div>
          </article>
        </div>

        <div v-else-if="activeEmbeddedView === 'rates'" class="embedded-panel-list">
          <article v-for="row in platforms" :key="row.id" class="embedded-trends-section">
            <div class="embedded-platform-title compact">
              <strong>{{ row.name }}</strong>
              <span>最近 7 天，按分组展示倍率变化</span>
            </div>
            <div class="embedded-trend-grid">
              <div
                v-for="series in platformRateHistory[row.id] ?? []"
                :key="series.group_id"
                class="embedded-trend-card"
              >
                <div class="embedded-trend-head">
                  <span>{{ series.group_name }}</span>
                  <strong>{{ latestRate(series) }}</strong>
                </div>
                <svg class="embedded-trend-chart" viewBox="0 0 320 96" role="img">
                  <polyline
                    v-if="chartPath(rateChartValues(series), 56)"
                    :points="chartPath(rateChartValues(series), 56)"
                    class="trend-line rate-line"
                  />
                  <g v-for="point in chartPoints(rateChartValues(series), 56)" :key="point.key">
                    <circle :cx="point.x" :cy="point.y" r="2.2" class="trend-dot rate-dot" />
                  </g>
                </svg>
                <div v-if="!hasChartData(rateChartValues(series))" class="embedded-trend-empty">
                  暂无历史
                </div>
              </div>
            </div>
          </article>
        </div>

        <div v-else class="embedded-panel-list">
          <article v-for="row in platforms" :key="row.id" class="embedded-platform-card">
            <header class="embedded-platform-header">
              <div class="embedded-platform-title">
                <div>
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.account_monitors.length }} 个账号 / {{ row.group_monitors.length }} 个分组</span>
                </div>
              </div>
              <div class="embedded-platform-controls">
                <el-button :icon="Setting" @click="openDetail(row)">配置监控项</el-button>
                <el-button :icon="Refresh" :loading="monitoring" type="primary" @click="runMonitor(row)">
                  立即采集
                </el-button>
              </div>
            </header>
          </article>
        </div>
      </main>
    </section>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑平台' : '新增平台'" width="620px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="112px">
        <el-form-item label="平台名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 主站 Sub2API" />
        </el-form-item>
        <el-form-item label="服务商类型" prop="provider_type">
          <el-select v-model="form.provider_type" class="full-width">
            <el-option
              v-for="provider in providers"
              :key="provider.value"
              :label="provider.label"
              :value="provider.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.provider_type === 'newapi'" label="站点策略" prop="site_strategy">
          <el-select v-model="form.site_strategy" class="full-width">
            <el-option
              v-for="strategy in siteStrategies"
              :key="strategy.value"
              :label="strategy.label"
              :value="strategy.value"
            >
              <span>{{ strategy.label }}</span>
              <span class="select-hint">{{ strategy.description }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="站点地址" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://relayai.tech/login" />
        </el-form-item>
        <el-form-item label="鉴权 Header" prop="auth_header_name">
          <el-input v-model="form.auth_header_name" />
        </el-form-item>
        <el-form-item label="鉴权前缀" prop="auth_header_prefix">
          <el-input v-model="form.auth_header_prefix" placeholder="Bearer" />
        </el-form-item>
        <el-form-item label="管理 API Key">
          <el-input
            v-model="form.api_key"
            placeholder="留空则不修改已有凭据"
            show-password
            type="password"
          />
        </el-form-item>
        <el-form-item label="余额 Cron" prop="balance_cron">
          <el-input v-model="form.balance_cron" placeholder="*/10 * * * *" />
        </el-form-item>
        <el-form-item label="倍率 Cron" prop="rate_cron">
          <el-input v-model="form.rate_cron" placeholder="0 * * * *" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button :loading="saving" type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="detail ? `监控项 - ${detail.name}` : '监控项'" width="980px">
      <div v-if="detail" class="monitor-config">
        <section>
          <div class="monitor-section-title">
            <div>
              <h3>余额趋势</h3>
              <p>每个账号最近 24 小时余额变化，按小时展示。</p>
            </div>
          </div>
          <div v-loading="historyLoading" class="history-grid">
            <div v-for="series in balanceHistory" :key="series.account_id" class="history-card">
              <div class="history-card-head">
                <span>{{ series.account_name }}</span>
                <strong>{{ latestBalance(series) }}</strong>
              </div>
              <svg class="trend-chart" viewBox="0 0 320 120" role="img">
                <polyline
                  v-if="chartPath(balanceChartValues(series))"
                  :points="chartPath(balanceChartValues(series))"
                  class="trend-line balance-line"
                />
                <g v-for="point in chartPoints(balanceChartValues(series))" :key="point.key">
                  <circle :cx="point.x" :cy="point.y" r="2.5" class="trend-dot balance-dot" />
                </g>
              </svg>
              <div class="history-axis">
                <span>{{ firstTimeLabel(series.points[0]?.at) }}</span>
                <span>最近 24 小时</span>
                <span>{{ firstTimeLabel(lastBalancePoint(series)?.at) }}</span>
              </div>
              <div v-if="!hasChartData(balanceChartValues(series))" class="history-empty">暂无余额历史</div>
            </div>
          </div>
        </section>

        <section>
          <div class="monitor-section-title">
            <div>
              <h3>倍率趋势</h3>
              <p>最近七天分组倍率变化。</p>
            </div>
          </div>
          <div v-loading="historyLoading" class="history-grid">
            <div v-for="series in rateHistory" :key="series.group_id" class="history-card">
              <div class="history-card-head">
                <span>{{ series.group_name }}</span>
                <strong>{{ latestRate(series) }}</strong>
              </div>
              <svg class="trend-chart" viewBox="0 0 320 120" role="img">
                <polyline
                  v-if="chartPath(rateChartValues(series))"
                  :points="chartPath(rateChartValues(series))"
                  class="trend-line rate-line"
                />
                <g v-for="point in chartPoints(rateChartValues(series))" :key="point.key">
                  <circle :cx="point.x" :cy="point.y" r="2.5" class="trend-dot rate-dot" />
                </g>
              </svg>
              <div class="history-axis">
                <span>{{ firstDateLabel(series.points[0]?.at) }}</span>
                <span>最近 7 天</span>
                <span>{{ firstDateLabel(lastRatePoint(series)?.at) }}</span>
              </div>
              <div v-if="!hasChartData(rateChartValues(series))" class="history-empty">暂无倍率历史</div>
            </div>
            <el-empty v-if="!historyLoading && rateHistory.length === 0" description="暂无分组倍率历史" />
          </div>
        </section>

        <section>
          <div class="monitor-section-title">
            <div>
              <h3>账号余额监控</h3>
              <p>配置一个或多个平台账号，用策略读取余额和额度剩余。</p>
            </div>
            <el-button :icon="Plus" @click="accountDialogVisible = true">添加账号</el-button>
          </div>
          <el-table :data="detail.account_monitors" size="small">
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column prop="external_account_id" label="平台账号 ID" min-width="160" />
            <el-table-column label="余额" width="120">
              <template #default="{ row }">{{ row.balance ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="已消耗" width="120">
              <template #default="{ row }">{{ formatMoney(row.quota_used) }}</template>
            </el-table-column>
            <el-table-column label="额度上限" width="120">
              <template #default="{ row }">{{ formatMoney(row.quota_limit) }}</template>
            </el-table-column>
            <el-table-column label="最后采集" width="170">
              <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
            </el-table-column>
            <el-table-column prop="last_error" label="错误" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button :icon="Delete" link type="danger" @click="removeAccount(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section>
          <div class="monitor-section-title">
            <div>
              <h3>分组倍率监控</h3>
              <p>配置指定分组，云锦策略填写 codex 即读取 group_ratio.codex。</p>
            </div>
            <el-button :icon="Plus" @click="groupDialogVisible = true">添加分组</el-button>
          </div>
          <el-table :data="detail.group_monitors" size="small">
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column prop="external_group_id" label="平台分组 ID" min-width="160" />
            <el-table-column label="倍率" width="100">
              <template #default="{ row }">{{ row.rate_multiplier ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="RPM" width="100">
              <template #default="{ row }">{{ row.rpm_limit ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="最后采集" width="170">
              <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
            </el-table-column>
            <el-table-column prop="last_error" label="错误" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button :icon="Delete" link type="danger" @click="removeGroup(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button :icon="Refresh" :loading="monitoring" @click="runDetailBalanceMonitor">采集余额</el-button>
        <el-button :icon="Refresh" :loading="monitoring" type="primary" @click="runDetailRateMonitor">采集倍率</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" title="添加账号余额监控" width="520px">
      <el-form :model="accountForm" label-width="110px">
        <el-form-item label="显示名称">
          <el-input v-model="accountForm.name" />
        </el-form-item>
        <el-form-item label="平台账号 ID">
          <el-input v-model="accountForm.external_account_id" />
        </el-form-item>
        <el-form-item label="登录账号">
          <el-input v-model="accountForm.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="登录密码">
          <el-input
            v-model="accountForm.password"
            autocomplete="new-password"
            placeholder="留空则不修改已有密码"
            show-password
            type="password"
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="accountForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="groupDialogVisible" title="添加分组倍率监控" width="520px">
      <el-form :model="groupForm" label-width="110px">
        <el-form-item label="显示名称">
          <el-input v-model="groupForm.name" />
        </el-form-item>
        <el-form-item label="平台分组 ID">
          <el-input v-model="groupForm.external_group_id" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="groupForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveGroup">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { Delete, Edit, Plus, Refresh, Setting } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createAccountMonitor,
  createGroupMonitor,
  createPlatform,
  deleteAccountMonitor,
  deleteGroupMonitor,
  deletePlatform,
  fetchBalanceHistory,
  fetchDashboard,
  fetchPlatform,
  fetchPlatforms,
  fetchProviders,
  fetchRateHistory,
  fetchSiteStrategies,
  runPlatformBalanceMonitor,
  runPlatformMonitor,
  runPlatformRateMonitor,
  updatePlatform,
  type AccountMonitorPayload,
  type AccountBalanceHistorySeries,
  type DashboardStats,
  type GroupRateHistorySeries,
  type GroupMonitorPayload,
  type PlatformDetail,
  type PlatformPayload,
  type PlatformStatus,
  type ProviderOption,
  type RelayPlatform,
  type SiteStrategyOption,
} from '@/api/client'

const providers = ref<ProviderOption[]>([])
const siteStrategies = ref<SiteStrategyOption[]>([])
const platforms = ref<PlatformDetail[]>([])
const stats = ref<DashboardStats | null>(null)
const detail = ref<PlatformDetail | null>(null)
const balanceHistory = ref<AccountBalanceHistorySeries[]>([])
const rateHistory = ref<GroupRateHistorySeries[]>([])
const platformBalanceHistory = ref<Record<number, AccountBalanceHistorySeries[]>>({})
const platformRateHistory = ref<Record<number, GroupRateHistorySeries[]>>({})
const loading = ref(false)
const historyLoading = ref(false)
const saving = ref(false)
const monitoring = ref(false)
const isEmbedded = ref(detectEmbedded())
const dialogVisible = ref(false)
const detailVisible = ref(false)
const accountDialogVisible = ref(false)
const groupDialogVisible = ref(false)
const editing = ref<RelayPlatform | null>(null)
const formRef = ref<FormInstance>()
const activeEmbeddedView = ref<'overview' | 'balances' | 'rates' | 'settings'>('overview')

const embeddedMenuItems = [
  {
    key: 'overview',
    label: '平台总览',
    description: '状态、账号余额和采集操作',
  },
  {
    key: 'balances',
    label: '余额趋势',
    description: '账号余额的小时级变化',
  },
  {
    key: 'rates',
    label: '倍率趋势',
    description: '分组倍率的周期变化',
  },
  {
    key: 'settings',
    label: '监控配置',
    description: '账号、分组和采集任务入口',
  },
] as const

const embeddedView = computed(
  () => embeddedMenuItems.find((item) => item.key === activeEmbeddedView.value) ?? embeddedMenuItems[0],
)
const embeddedViewTitle = computed(() => embeddedView.value.label)
const embeddedViewDescription = computed(() => embeddedView.value.description)

const form = reactive<PlatformPayload>({
  name: '',
  base_url: '',
  provider_type: 'sub2api',
  site_strategy: 'generic',
  auth_header_name: 'Authorization',
  auth_header_prefix: 'Bearer',
  api_key: null,
  balance_cron: '*/10 * * * *',
  rate_cron: '0 * * * *',
  enabled: true,
  key_count: 0,
  balance: null,
  quota_used: null,
  quota_limit: null,
})

const accountForm = reactive<AccountMonitorPayload>({
  name: '',
  external_account_id: '',
  username: null,
  password: null,
  enabled: true,
})

const groupForm = reactive<GroupMonitorPayload>({
  name: '',
  external_group_id: '',
  enabled: true,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入平台名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入站点地址', trigger: 'blur' }],
  provider_type: [{ required: true, message: '请选择服务商类型', trigger: 'change' }],
  site_strategy: [{ required: true, message: '请选择站点策略', trigger: 'change' }],
  auth_header_name: [{ required: true, message: '请输入鉴权 Header', trigger: 'blur' }],
  balance_cron: [{ required: true, message: '请输入余额 Cron', trigger: 'blur' }],
  rate_cron: [{ required: true, message: '请输入倍率 Cron', trigger: 'blur' }],
}

function detectEmbedded() {
  try {
    return window.self !== window.top || new URLSearchParams(window.location.search).has('embedded')
  } catch {
    return true
  }
}

function resetForm() {
  Object.assign(form, {
    name: '',
    base_url: '',
    provider_type: 'sub2api',
    site_strategy: 'generic',
    auth_header_name: 'Authorization',
    auth_header_prefix: 'Bearer',
    api_key: null,
    balance_cron: '*/10 * * * *',
    rate_cron: '0 * * * *',
    enabled: true,
    key_count: 0,
    balance: null,
    quota_used: null,
    quota_limit: null,
  })
}

function resetAccountForm() {
  Object.assign(accountForm, {
    name: '',
    external_account_id: '',
    username: null,
    password: null,
    enabled: true,
  })
}

function resetGroupForm() {
  Object.assign(groupForm, { name: '', external_group_id: '', enabled: true })
}

function openCreate() {
  editing.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: RelayPlatform) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    base_url: row.base_url,
    provider_type: row.provider_type,
    site_strategy: row.site_strategy,
    auth_header_name: row.auth_header_name,
    auth_header_prefix: row.auth_header_prefix,
    api_key: null,
    balance_cron: row.balance_cron,
    rate_cron: row.rate_cron,
    enabled: row.enabled,
    key_count: row.key_count,
    balance: row.balance,
    quota_used: row.quota_used,
    quota_limit: row.quota_limit,
  })
  dialogVisible.value = true
}

async function openDetail(row: RelayPlatform) {
  detail.value = await fetchPlatform(row.id)
  await loadHistory(row.id)
  detailVisible.value = true
}

async function load() {
  loading.value = true
  try {
    const [providerRows, siteStrategyRows, dashboard, rows] = await Promise.all([
      fetchProviders(),
      fetchSiteStrategies(),
      fetchDashboard(),
      fetchPlatforms(),
    ])
    const details = await Promise.all(rows.map((row) => fetchPlatform(row.id)))
    providers.value = providerRows
    siteStrategies.value = siteStrategyRows
    stats.value = dashboard
    platforms.value = details
    if (isEmbedded.value) {
      await loadPlatformHistories(details.map((row) => row.id))
    }
  } finally {
    loading.value = false
  }
}

async function reloadDetail() {
  if (!detail.value) {
    return
  }
  detail.value = await fetchPlatform(detail.value.id)
  await loadHistory(detail.value.id)
}

async function loadHistory(platformId: number) {
  historyLoading.value = true
  try {
    const [balances, rates] = await Promise.all([
      fetchBalanceHistory(platformId),
      fetchRateHistory(platformId),
    ])
    balanceHistory.value = balances
    rateHistory.value = rates
    platformBalanceHistory.value = { ...platformBalanceHistory.value, [platformId]: balances }
    platformRateHistory.value = { ...platformRateHistory.value, [platformId]: rates }
  } finally {
    historyLoading.value = false
  }
}

async function loadPlatformHistories(platformIds: number[]) {
  historyLoading.value = true
  try {
    const rows = await Promise.all(
      platformIds.map(async (platformId) => {
        const [balances, rates] = await Promise.all([
          fetchBalanceHistory(platformId),
          fetchRateHistory(platformId),
        ])
        return { platformId, balances, rates }
      }),
    )
    platformBalanceHistory.value = Object.fromEntries(
      rows.map((row) => [row.platformId, row.balances]),
    )
    platformRateHistory.value = Object.fromEntries(rows.map((row) => [row.platformId, row.rates]))
  } finally {
    historyLoading.value = false
  }
}

async function save() {
  await formRef.value?.validate()
  saving.value = true
  try {
    const payload = { ...form }
    if (payload.provider_type !== 'newapi') {
      payload.site_strategy = 'generic'
    }
    if (!payload.api_key) {
      delete payload.api_key
    }
    if (editing.value) {
      await updatePlatform(editing.value.id, payload)
    } else {
      await createPlatform(payload)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row: RelayPlatform) {
  await updatePlatform(row.id, { enabled: !row.enabled })
  await load()
}

async function remove(row: RelayPlatform) {
  await ElMessageBox.confirm(`确认删除平台「${row.name}」？`, '删除确认', { type: 'warning' })
  await deletePlatform(row.id)
  ElMessage.success('已删除')
  await load()
}

async function runMonitor(row: RelayPlatform) {
  monitoring.value = true
  try {
    await runPlatformMonitor(row.id)
    ElMessage.success('采集完成')
    await load()
    if (isEmbedded.value) {
      await loadHistory(row.id)
    }
  } finally {
    monitoring.value = false
  }
}

async function runDetailMonitor() {
  if (!detail.value) {
    return
  }
  monitoring.value = true
  try {
    await runPlatformMonitor(detail.value.id)
    ElMessage.success('采集完成')
    await reloadDetail()
    await load()
  } finally {
    monitoring.value = false
  }
}

async function runDetailBalanceMonitor() {
  if (!detail.value) {
    return
  }
  monitoring.value = true
  try {
    await runPlatformBalanceMonitor(detail.value.id)
    ElMessage.success('余额采集完成')
    await reloadDetail()
    await load()
  } finally {
    monitoring.value = false
  }
}

async function runDetailRateMonitor() {
  if (!detail.value) {
    return
  }
  monitoring.value = true
  try {
    await runPlatformRateMonitor(detail.value.id)
    ElMessage.success('倍率采集完成')
    await reloadDetail()
    await load()
  } finally {
    monitoring.value = false
  }
}

async function saveAccount() {
  if (!detail.value || !accountForm.name) {
    ElMessage.error('请填写账号名称')
    return
  }
  if (!accountForm.external_account_id && !accountForm.username) {
    ElMessage.error('请填写平台账号 ID 或登录账号')
    return
  }
  const payload = {
    ...accountForm,
    external_account_id: accountForm.external_account_id || accountForm.username || accountForm.name,
  }
  if (!payload.password) {
    delete payload.password
  }
  await createAccountMonitor(detail.value.id, payload)
  resetAccountForm()
  accountDialogVisible.value = false
  await reloadDetail()
  await load()
}

async function removeAccount(monitorId: number) {
  if (!detail.value) {
    return
  }
  await deleteAccountMonitor(detail.value.id, monitorId)
  await reloadDetail()
  await load()
}

async function saveGroup() {
  if (!detail.value || !groupForm.name || !groupForm.external_group_id) {
    ElMessage.error('请填写分组名称和平台分组 ID')
    return
  }
  await createGroupMonitor(detail.value.id, groupForm)
  resetGroupForm()
  groupDialogVisible.value = false
  await reloadDetail()
  await load()
}

async function removeGroup(monitorId: number) {
  if (!detail.value) {
    return
  }
  await deleteGroupMonitor(detail.value.id, monitorId)
  await reloadDetail()
  await load()
}

function providerLabel(providerType: string) {
  return providers.value.find((item) => item.value === providerType)?.label ?? providerType
}

function siteStrategyLabel(row: RelayPlatform) {
  if (row.provider_type !== 'newapi') {
    return '默认'
  }
  return siteStrategies.value.find((item) => item.value === row.site_strategy)?.label ?? row.site_strategy
}

function statusType(status: PlatformStatus) {
  return {
    healthy: 'success',
    degraded: 'warning',
    down: 'danger',
    unknown: 'info',
  }[status]
}

function statusText(status: PlatformStatus) {
  return {
    healthy: '健康',
    degraded: '降级',
    down: '不可用',
    unknown: '未知',
  }[status]
}

function formatMoney(value: number | null) {
  if (value === null) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatTime(value: string | null) {
  if (!value) {
    return '-'
  }
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

function firstTimeLabel(value: string | undefined) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function firstDateLabel(value: string | undefined) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function balanceChartValues(series: AccountBalanceHistorySeries) {
  return series.points.map((point) => point.balance)
}

function rateChartValues(series: GroupRateHistorySeries) {
  return series.points.map((point) => point.rate_multiplier)
}

function lastBalancePoint(series: AccountBalanceHistorySeries) {
  return series.points[series.points.length - 1]
}

function lastRatePoint(series: GroupRateHistorySeries) {
  return series.points[series.points.length - 1]
}

function hasChartData(values: Array<number | null>) {
  return values.some((value) => value !== null)
}

function chartPoints(values: Array<number | null>, chartHeight = 76) {
  const validValues = values.filter((value): value is number => value !== null)
  if (validValues.length === 0) {
    return []
  }
  const min = Math.min(...validValues)
  const max = Math.max(...validValues)
  const range = max - min || 1
  const width = 280
  const height = chartHeight
  const xStart = 20
  const yStart = 20
  const step = values.length > 1 ? width / (values.length - 1) : width

  return values
    .map((value, index) => {
      if (value === null) {
        return null
      }
      return {
        key: `${index}-${value}`,
        x: xStart + step * index,
        y: yStart + height - ((value - min) / range) * height,
      }
    })
    .filter((point): point is { key: string; x: number; y: number } => point !== null)
}

function chartPath(values: Array<number | null>, chartHeight = 76) {
  return chartPoints(values, chartHeight)
    .map((point) => `${point.x},${point.y}`)
    .join(' ')
}

function latestBalance(series: AccountBalanceHistorySeries) {
  const latest = [...series.points].reverse().find((point) => point.balance !== null)
  return latest ? formatMoney(latest.balance) : '-'
}

function latestRate(series: GroupRateHistorySeries) {
  const latest = [...series.points].reverse().find((point) => point.rate_multiplier !== null)
  return latest?.rate_multiplier ?? '-'
}

onMounted(load)
</script>
