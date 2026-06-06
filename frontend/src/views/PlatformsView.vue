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
                <div class="account-compare-main">
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
                  <div class="account-compare-meta">
                    <span><em>账号</em>{{ account.external_account_id }}</span>
                    <span v-if="accountLoginLabel(account)">
                      <em>登录</em>{{ accountLoginLabel(account) }}
                    </span>
                  </div>
                  <div v-if="account.last_error" class="account-compare-error">
                    {{ account.last_error }}
                  </div>
                </div>
                <div class="account-compare-metrics">
                  <span><em>余额</em> {{ formatMoney(account.balance) }}</span>
                  <span><em>消耗</em> {{ formatMoney(account.quota_used) }}</span>
                </div>
                <div v-if="visibleAccountKeys(account).length > 0" class="account-key-summary-list account-key-summary-row">
                  <span
                    v-for="key in visibleAccountKeys(account)"
                    :key="accountKeySummaryId(key)"
                    class="account-key-summary"
                  >
                    <strong>{{ key.name }}</strong>
                    <em>{{ keyGroupLabel(key) }}</em>
                  </span>
                  <span v-if="hiddenAccountKeyCount(account) > 0" class="account-key-summary more">
                    +{{ hiddenAccountKeyCount(account) }}
                  </span>
                </div>
                <div v-else class="account-key-empty">暂无密钥</div>
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
        <el-table-column label="充值/到账" width="150">
          <template #default="{ row }">
            <div class="rate-conversion-cell">
              <strong>{{ formatRateConversion(row) }}</strong>
              <span>系数 {{ formatMultiplier(row.effective_rate_factor) }}</span>
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
                      <div class="embedded-account-meta">
                        <span><em>账号</em>{{ account.external_account_id }}</span>
                        <span v-if="accountLoginLabel(account)">
                          <em>登录</em>{{ accountLoginLabel(account) }}
                        </span>
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
                    <div class="embedded-account-key-panel">
                      <span class="embedded-account-key-title">密钥 / 分组</span>
                      <div
                        v-if="visibleAccountKeys(account).length > 0"
                        class="account-key-summary-list embedded-account-keys"
                      >
                        <span
                          v-for="key in visibleAccountKeys(account)"
                          :key="accountKeySummaryId(key)"
                          class="account-key-summary"
                        >
                          <strong>{{ key.name }}</strong>
                          <em>{{ keyGroupLabel(key) }}</em>
                        </span>
                        <span v-if="hiddenAccountKeyCount(account) > 0" class="account-key-summary more">
                          +{{ hiddenAccountKeyCount(account) }}
                        </span>
                      </div>
                      <span v-else class="account-key-empty">暂无密钥</span>
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
                <div>
                  <span>充值/到账</span>
                  <strong>{{ formatRateConversion(row) }}</strong>
                </div>
                <div>
                  <span>充值倍率系数</span>
                  <strong>{{ formatMultiplier(row.effective_rate_factor) }}</strong>
                </div>
              </div>

              <div class="embedded-group-rate-panel">
                <div class="embedded-section-label">接口分组速览</div>
                <div
                  v-if="overviewDiscoveredGroupRates(row.discovered_group_rates).length > 0"
                  class="embedded-group-rate-list"
                >
                  <div
                    v-for="group in overviewDiscoveredGroupRates(row.discovered_group_rates)"
                    :key="group.external_group_id"
                    class="embedded-group-rate-row"
                    :class="{ highlighted: group.is_configured }"
                  >
                    <div class="embedded-group-rate-main">
                      <div class="embedded-group-rate-title">
                        <strong>{{ group.name }}</strong>
                        <div class="embedded-group-rate-tags">
                          <el-tag v-if="group.is_highest" size="small" type="success" effect="light">最高</el-tag>
                          <el-tag v-if="group.is_lowest" size="small" type="info" effect="light">最低</el-tag>
                          <el-tag v-if="group.is_configured" size="small" type="warning" effect="light">监控</el-tag>
                        </div>
                      </div>
                      <span>{{ group.external_group_id }}</span>
                      <span v-if="group.description" class="embedded-group-rate-desc">{{ group.description }}</span>
                    </div>
                    <div class="embedded-group-rate-values">
                      <div>
                        <span>原始倍率</span>
                        <strong>{{ formatMultiplier(group.rate_multiplier) }}</strong>
                      </div>
                      <div>
                        <span>实际倍率</span>
                        <strong>{{ formatMultiplier(group.effective_rate_multiplier) }}</strong>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="embedded-empty">暂无接口分组</div>
              </div>

              <div v-if="row.provider_type === 'newapi'" class="embedded-group-rate-panel">
                <div class="embedded-section-label">渠道倍率速览</div>
                <div
                  v-if="overviewDiscoveredChannelRates(row.discovered_channel_rates).length > 0"
                  class="embedded-group-rate-list"
                >
                  <div
                    v-for="channel in overviewDiscoveredChannelRates(row.discovered_channel_rates)"
                    :key="channel.external_channel_id"
                    class="embedded-group-rate-row"
                  >
                    <div class="embedded-group-rate-main">
                      <div class="embedded-group-rate-title">
                        <strong>{{ channel.name }}</strong>
                        <div class="embedded-group-rate-tags">
                          <el-tag v-if="channel.is_highest" size="small" type="success" effect="light">最高</el-tag>
                          <el-tag v-if="channel.is_lowest" size="small" type="info" effect="light">最低</el-tag>
                          <el-tag v-if="channel.status" size="small" type="info" effect="light">
                            {{ channel.status }}
                          </el-tag>
                        </div>
                      </div>
                      <span>渠道 {{ channel.external_channel_id }}</span>
                      <span v-if="channel.base_url" class="embedded-group-rate-desc">{{ channel.base_url }}</span>
                      <span v-if="channel.description" class="embedded-group-rate-desc">
                        {{ channel.description }}
                      </span>
                    </div>
                    <div class="embedded-group-rate-values">
                      <div>
                        <span>平均倍率</span>
                        <strong>{{ formatMultiplier(channel.rate_multiplier) }}</strong>
                      </div>
                      <div>
                        <span>模型数</span>
                        <strong>{{ channelModelRateCount(channel) }}</strong>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="embedded-empty">暂无渠道倍率</div>
              </div>
            </div>
          </article>
          <el-empty v-if="!loading && platforms.length === 0" description="暂无平台" />
        </div>

        <div v-else-if="activeEmbeddedView === 'balances'" class="embedded-panel-list">
          <article v-for="row in platforms" :key="row.id" class="embedded-trends-section">
            <div class="embedded-platform-title compact">
              <strong>{{ row.name }}</strong>
              <span>最近 24 小时，按平台和账号展示真实采样点：{{ row.balance_cron }}</span>
            </div>
            <div class="embedded-trend-grid balance-trend-grid">
              <div
                v-for="series in platformBalanceHistory[row.id] ?? []"
                :key="series.account_id"
                class="embedded-trend-card balance-trend-card"
              >
                <div class="embedded-trend-head">
                  <span>{{ series.account_name }}</span>
                  <strong>{{ latestBalance(series) }}</strong>
                </div>
                <BalanceLineChart :series="series" />
                <div v-if="!hasChartData(balanceChartValues(series))" class="embedded-trend-empty">
                  暂无历史
                </div>
              </div>
            </div>
          </article>
        </div>

        <div v-else-if="activeEmbeddedView === 'rates'" class="embedded-panel-list">
          <article v-for="row in platforms" :key="row.id" class="embedded-trends-section embedded-rate-section">
            <div class="embedded-platform-title compact embedded-rate-header">
              <div>
                <strong>{{ row.name }}</strong>
                <span>{{ row.base_url }}</span>
              </div>
              <span>分组倍率趋势</span>
            </div>
            <div v-if="rateHistoryVisibleSeries(row.id).length > 0" class="embedded-rate-platform-card">
              <RateLineChart :series="rateHistoryVisibleSeries(row.id)" />
              <div class="history-axis rate-history-axis">
                <span>{{ platformRateFirstDate(row.id) }}</span>
                <span>分组趋势</span>
                <span>{{ platformRateLastDate(row.id) }}</span>
              </div>
            </div>
            <div v-else class="embedded-empty">暂无分组趋势</div>
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
          <el-select v-model="form.provider_type" class="full-width" @change="onProviderTypeChange">
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
        <el-form-item v-if="form.provider_type !== 'newapi'" label="鉴权前缀" prop="auth_header_prefix">
          <el-input v-model="form.auth_header_prefix" placeholder="Bearer" />
        </el-form-item>
        <el-form-item :label="form.provider_type === 'newapi' ? 'Access Token' : '管理 API Key'">
          <el-input
            v-model="form.api_key"
            :placeholder="form.provider_type === 'newapi' ? 'Access Token，可带或不带 Bearer' : '留空则不修改已有凭据'"
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
        <el-form-item label="充值金额" prop="recharge_amount">
          <el-input-number
            v-model="form.recharge_amount"
            :min="0.000001"
            :precision="6"
            :step="1"
            class="full-width"
          />
        </el-form-item>
        <el-form-item label="到账金额" prop="received_amount">
          <el-input-number
            v-model="form.received_amount"
            :min="0.000001"
            :precision="6"
            :step="1"
            class="full-width"
          />
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
              <h3>账号余额监控</h3>
              <p>配置一个或多个平台账号，用策略读取余额和额度剩余。</p>
            </div>
            <el-button :icon="Plus" @click="openAccountCreate">添加账号</el-button>
          </div>
          <el-table :data="detail.account_monitors" size="small">
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column prop="external_account_id" label="平台账号 ID" min-width="160" />
            <el-table-column label="密钥 / 分组" min-width="220">
              <template #default="{ row }">
                <div v-if="visibleAccountKeys(row).length > 0" class="account-key-summary-list detail">
                  <span
                    v-for="key in visibleAccountKeys(row)"
                    :key="accountKeySummaryId(key)"
                    class="account-key-summary"
                  >
                    <strong>{{ key.name }}</strong>
                    <em>{{ keyGroupLabel(key) }}</em>
                  </span>
                  <span v-if="hiddenAccountKeyCount(row) > 0" class="account-key-summary more">
                    +{{ hiddenAccountKeyCount(row) }}
                  </span>
                </div>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
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
                <el-button :icon="Edit" link @click="openAccountEdit(row)">编辑</el-button>
                <el-button :icon="Delete" link type="danger" @click="removeAccount(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section>
          <div class="monitor-section-title">
            <div>
              <h3>接口分组倍率</h3>
              <p>展示接口返回的全部分组倍率，已监控分组会高亮。</p>
            </div>
          </div>
          <div
            v-if="uniqueDiscoveredGroupRates(detail.discovered_group_rates).length > 0"
            class="embedded-group-rate-list"
          >
            <div
              v-for="group in uniqueDiscoveredGroupRates(detail.discovered_group_rates)"
              :key="group.external_group_id"
              class="embedded-group-rate-row"
              :class="{ highlighted: group.is_configured }"
            >
              <div class="embedded-group-rate-main">
                <strong>{{ group.name }}</strong>
                <span>{{ group.external_group_id }}</span>
                <span v-if="group.description" class="embedded-group-rate-desc">{{ group.description }}</span>
              </div>
              <div class="embedded-group-rate-values">
                <div>
                  <span>原始倍率</span>
                  <strong>{{ formatMultiplier(group.rate_multiplier) }}</strong>
                </div>
                <div>
                  <span>实际倍率</span>
                  <strong>{{ formatMultiplier(group.effective_rate_multiplier) }}</strong>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无接口分组" />
        </section>

        <section v-if="detail.provider_type === 'newapi'">
          <div class="monitor-section-title">
            <div>
              <h3>渠道倍率</h3>
              <p>展示 New API 渠道同步接口返回的模型倍率，平均倍率按已返回模型计算。</p>
            </div>
          </div>
          <div
            v-if="uniqueDiscoveredChannelRates(detail.discovered_channel_rates).length > 0"
            class="embedded-group-rate-list"
          >
            <div
              v-for="channel in uniqueDiscoveredChannelRates(detail.discovered_channel_rates)"
              :key="channel.external_channel_id"
              class="embedded-group-rate-row channel-rate-row"
            >
              <div class="embedded-group-rate-main">
                <div class="embedded-group-rate-title">
                  <strong>{{ channel.name }}</strong>
                  <div class="embedded-group-rate-tags">
                    <el-tag v-if="channel.status" size="small" type="info" effect="light">
                      {{ channel.status }}
                    </el-tag>
                  </div>
                </div>
                <span>渠道 {{ channel.external_channel_id }}</span>
                <span v-if="channel.base_url" class="embedded-group-rate-desc">{{ channel.base_url }}</span>
                <span v-if="channel.description" class="embedded-group-rate-desc">{{ channel.description }}</span>
                <div v-if="channelModelRateEntries(channel).length > 0" class="channel-model-rate-list">
                  <span
                    v-for="[model, rate] in channelModelRateEntries(channel)"
                    :key="`${channel.external_channel_id}:${model}`"
                    class="channel-model-rate"
                  >
                    <strong>{{ model }}</strong>
                    <em>{{ formatMultiplier(rate) }}</em>
                  </span>
                </div>
              </div>
              <div class="embedded-group-rate-values">
                <div>
                  <span>平均倍率</span>
                  <strong>{{ formatMultiplier(channel.rate_multiplier) }}</strong>
                </div>
                <div>
                  <span>模型数</span>
                  <strong>{{ channelModelRateCount(channel) }}</strong>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无渠道倍率" />
        </section>

        <section>
          <div class="monitor-section-title">
            <div>
              <h3>已监控分组</h3>
              <p>配置指定分组，云锦策略填写 codex 即读取 group_ratio.codex。</p>
            </div>
            <el-button :icon="Plus" @click="groupDialogVisible = true">添加分组</el-button>
          </div>
          <el-table :data="detail.group_monitors" size="small">
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column prop="external_group_id" label="平台分组 ID" min-width="160" />
            <el-table-column label="原始倍率" width="110">
              <template #default="{ row }">{{ formatMultiplier(row.rate_multiplier) }}</template>
            </el-table-column>
            <el-table-column label="实际倍率" width="110">
              <template #default="{ row }">
                <strong>{{ formatMultiplier(row.effective_rate_multiplier) }}</strong>
              </template>
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

    <el-dialog v-model="accountDialogVisible" :title="accountEditing ? '编辑账号余额监控' : '添加账号余额监控'" width="520px">
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

import BalanceLineChart from '@/components/BalanceLineChart.vue'
import RateLineChart from '@/components/RateLineChart.vue'
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
  updateAccountMonitor,
  updatePlatform,
  type AccountKeySummary,
  type AccountMonitor,
  type AccountMonitorPayload,
  type AccountBalanceHistorySeries,
  type DashboardStats,
  type DiscoveredChannelRate,
  type DiscoveredGroupRate,
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
const accountEditing = ref<AccountMonitor | null>(null)
const formRef = ref<FormInstance>()
const activeEmbeddedView = ref<'overview' | 'balances' | 'rates' | 'settings'>('overview')
const maxAccountKeysShown = 3

const embeddedMenuItems = [
  {
    key: 'overview',
    label: '平台总览',
    description: '状态、账号余额和采集操作',
  },
  {
    key: 'balances',
    label: '余额趋势',
    description: '账号余额按 cron 间隔变化',
  },
  {
    key: 'rates',
    label: '倍率趋势',
    description: '按平台展示分组趋势',
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
  recharge_amount: 1,
  received_amount: 1,
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
  recharge_amount: [{ required: true, message: '请输入充值金额', trigger: 'blur' }],
  received_amount: [{ required: true, message: '请输入到账金额', trigger: 'blur' }],
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
    recharge_amount: 1,
    received_amount: 1,
    enabled: true,
    key_count: 0,
    balance: null,
    quota_used: null,
    quota_limit: null,
  })
}

function onProviderTypeChange(value: string | number | boolean | undefined) {
  if (value === 'newapi') {
    form.auth_header_name = 'Authorization'
    form.auth_header_prefix = 'Bearer'
    return
  }
  if (!form.auth_header_prefix) {
    form.auth_header_prefix = 'Bearer'
  }
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

function openAccountCreate() {
  accountEditing.value = null
  resetAccountForm()
  accountDialogVisible.value = true
}

function openAccountEdit(row: AccountMonitor) {
  accountEditing.value = row
  Object.assign(accountForm, {
    name: row.name,
    external_account_id: row.external_account_id,
    username: row.username,
    password: null,
    enabled: row.enabled,
  })
  accountDialogVisible.value = true
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
    recharge_amount: row.recharge_amount,
    received_amount: row.received_amount,
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
      await loadEmbeddedHistories(details.map((row) => row.id))
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
}

async function loadPlatformBalanceHistories(platformIds: number[]) {
  const rows = await Promise.all(
    platformIds.map(async (platformId) => ({
      platformId,
      balances: await fetchBalanceHistory(platformId),
    })),
  )
  platformBalanceHistory.value = Object.fromEntries(rows.map((row) => [row.platformId, row.balances]))
}

async function loadPlatformRateHistories(platformIds: number[]) {
  const rows = await Promise.all(
    platformIds.map(async (platformId) => ({
      platformId,
      rates: await fetchRateHistory(platformId),
    })),
  )
  platformRateHistory.value = Object.fromEntries(rows.map((row) => [row.platformId, row.rates]))
}

async function loadEmbeddedHistories(platformIds: number[]) {
  historyLoading.value = true
  try {
    await Promise.all([loadPlatformBalanceHistories(platformIds), loadPlatformRateHistories(platformIds)])
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
    } else if (!payload.auth_header_prefix) {
      payload.auth_header_prefix = 'Bearer'
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
  if (accountEditing.value) {
    await updateAccountMonitor(detail.value.id, accountEditing.value.id, payload)
  } else {
    await createAccountMonitor(detail.value.id, payload)
  }
  resetAccountForm()
  accountEditing.value = null
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

function accountKeySummaries(account: AccountMonitor) {
  return account.key_summaries ?? []
}

function visibleAccountKeys(account: AccountMonitor) {
  return accountKeySummaries(account).slice(0, maxAccountKeysShown)
}

function hiddenAccountKeyCount(account: AccountMonitor) {
  return Math.max(accountKeySummaries(account).length - maxAccountKeysShown, 0)
}

function accountLoginLabel(account: AccountMonitor) {
  if (!account.username || account.username === account.external_account_id) {
    return ''
  }
  return account.username
}

function accountKeySummaryId(key: AccountKeySummary) {
  return key.id || `${key.name}:${key.group_id ?? ''}:${key.group_name ?? ''}`
}

function keyGroupLabel(key: AccountKeySummary) {
  return key.group_name || (key.group_id ? `分组 ${key.group_id}` : '未绑定分组')
}

function formatMoney(value: number | null) {
  if (value === null) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatMultiplier(value: number | null) {
  if (value === null) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatRateConversion(row: RelayPlatform) {
  return `${formatMultiplier(row.recharge_amount)} / ${formatMultiplier(row.received_amount)}`
}

function uniqueDiscoveredGroupRates(rows: DiscoveredGroupRate[]) {
  const seen = new Map<string, DiscoveredGroupRate>()
  for (const row of rows) {
    seen.set(row.external_group_id, row)
  }
  return Array.from(seen.values())
}

function uniqueDiscoveredChannelRates(rows: DiscoveredChannelRate[]) {
  const seen = new Map<string, DiscoveredChannelRate>()
  for (const row of rows) {
    seen.set(row.external_channel_id, row)
  }
  return Array.from(seen.values())
}

function rateHistoryVisibleSeries(platformId: number) {
  return platformRateHistory.value[platformId] ?? []
}

function platformRatePrimarySeries(platformId: number) {
  return rateHistoryVisibleSeries(platformId)[0] ?? null
}

function platformRateFirstDate(platformId: number) {
  return firstDateLabel(platformRatePrimarySeries(platformId)?.points[0]?.at)
}

function platformRateLastDate(platformId: number) {
  const series = platformRatePrimarySeries(platformId)
  return firstDateLabel(series?.points[series.points.length - 1]?.at)
}

type OverviewDiscoveredGroupRate = DiscoveredGroupRate & {
  is_highest: boolean
  is_lowest: boolean
}

type OverviewDiscoveredChannelRate = DiscoveredChannelRate & {
  is_highest: boolean
  is_lowest: boolean
}

function overviewDiscoveredGroupRates(rows: DiscoveredGroupRate[]): OverviewDiscoveredGroupRate[] {
  const unique = uniqueDiscoveredGroupRates(rows)
  const configured = unique.filter((row) => row.is_configured)
  const ranked = unique
    .filter((row) => row.rate_multiplier !== null)
    .slice()
    .sort((a, b) => (a.rate_multiplier ?? 0) - (b.rate_multiplier ?? 0))
  const highest = ranked[ranked.length - 1]
  const lowest = ranked[0]
  const selected = [...configured, highest, lowest].filter(
    (row): row is DiscoveredGroupRate => row !== undefined,
  )
  const seen = new Set<string>()
  return selected.filter((row) => {
    if (seen.has(row.external_group_id)) {
      return false
    }
    seen.add(row.external_group_id)
    return true
  }).map((row) => ({
    ...row,
    is_highest: row.external_group_id === highest?.external_group_id,
    is_lowest: row.external_group_id === lowest?.external_group_id,
  }))
}

function overviewDiscoveredChannelRates(rows: DiscoveredChannelRate[]): OverviewDiscoveredChannelRate[] {
  const unique = uniqueDiscoveredChannelRates(rows)
  const ranked = unique
    .filter((row) => row.rate_multiplier !== null)
    .slice()
    .sort((a, b) => (a.rate_multiplier ?? 0) - (b.rate_multiplier ?? 0))
  const highest = ranked[ranked.length - 1]
  const lowest = ranked[0]
  const selected = [highest, lowest].filter(
    (row): row is DiscoveredChannelRate => row !== undefined,
  )
  const fallback = selected.length > 0 ? selected : unique.slice(0, 2)
  const seen = new Set<string>()
  return fallback.filter((row) => {
    if (seen.has(row.external_channel_id)) {
      return false
    }
    seen.add(row.external_channel_id)
    return true
  }).map((row) => ({
    ...row,
    is_highest: row.external_channel_id === highest?.external_channel_id,
    is_lowest: row.external_channel_id === lowest?.external_channel_id,
  }))
}

function channelModelRateEntries(row: DiscoveredChannelRate) {
  return Object.entries(row.model_rates ?? {}).slice(0, 8)
}

function channelModelRateCount(row: DiscoveredChannelRate) {
  return Object.keys(row.model_rates ?? {}).length
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

function firstDateLabel(value: string | undefined) {
  if (!value) {
    return '-'
  }
  const date = parseApiTime(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return date.toLocaleDateString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    timeZone: 'Asia/Shanghai',
  })
}

function parseApiTime(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(normalized)
}

function balanceChartValues(series: AccountBalanceHistorySeries) {
  return series.points.map((point) => point.balance)
}

function hasChartData(values: Array<number | null>) {
  return values.some((value) => value !== null)
}

function latestBalance(series: AccountBalanceHistorySeries) {
  const latest = [...series.points].reverse().find((point) => point.balance !== null)
  return latest ? formatMoney(latest.balance) : '-'
}

onMounted(load)
</script>
