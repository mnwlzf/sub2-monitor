<template>
  <div v-loading="loading" class="platforms-page embedded-render">
        <div class="embedded-render-head">
          <div>
            <h3>{{ embeddedViewTitle }}</h3>
            <p>{{ embeddedViewDescription }}</p>
          </div>
          <el-button :icon="Plus" size="small" type="primary" @click="openCreate">新增平台</el-button>
        </div>

        <div v-if="activeEmbeddedView === 'overview'" class="embedded-panel-list">
          <section class="ops-summary">
            <div class="ops-summary-main">
              <div>
                <span>今日总消耗</span>
                <strong>{{ formatUsagePair(stats?.today_quota_used ?? null, stats?.today_actual_used ?? null) }}</strong>
                <em>平台扣减 / 实际扣减</em>
              </div>
              <div class="ops-summary-actions">
                <el-button
                  :disabled="errorSummaryItems.length === 0"
                  :type="errorSummaryItems.length > 0 ? 'danger' : 'primary'"
                  plain
                  @click="errorDialogVisible = true"
                >
                  异常 {{ errorSummaryItems.length }}
                </el-button>
                <el-button :icon="Refresh" :loading="monitoring" type="primary" @click="runAllEnabledMonitors">
                  全部采集
                </el-button>
              </div>
            </div>
            <div class="ops-kpi-grid">
              <div v-for="item in overviewKpis" :key="item.key" class="ops-kpi" :class="item.tone">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <em>{{ item.detail }}</em>
              </div>
            </div>
          </section>

          <section class="ops-focus-grid">
            <article class="ops-focus-card">
              <span>最高消耗平台</span>
              <strong>{{ topSpendingPlatform?.name ?? '-' }}</strong>
              <div class="ops-focus-values">
                <small>今日 {{ formatUsagePair(topSpendingPlatform?.today_quota_used ?? null, topSpendingPlatform?.today_actual_used ?? null) }}</small>
                <small>余额 {{ formatMoney(topSpendingPlatform?.balance ?? null) }}</small>
              </div>
            </article>
            <article class="ops-focus-card">
              <span>最低余额账号</span>
              <strong>{{ lowestBalanceAccount?.account.name ?? '-' }}</strong>
              <div class="ops-focus-values">
                <small>{{ lowestBalanceAccount?.platform.name ?? '-' }}</small>
                <small>{{ formatMoney(lowestBalanceAccount?.account.balance ?? null) }}</small>
              </div>
            </article>
            <article class="ops-focus-card">
              <span>分组倍率差</span>
              <strong>{{ formatMultiplier(groupRateSpread.spread) }}</strong>
              <div class="ops-focus-values">
                <small>最低 {{ groupRateSpread.lowLabel }}</small>
                <small>最高 {{ groupRateSpread.highLabel }}</small>
              </div>
            </article>
            <article class="ops-focus-card">
              <span>渠道倍率差</span>
              <strong>{{ formatMultiplier(channelRateSpread.spread) }}</strong>
              <div class="ops-focus-values">
                <small>最低 {{ channelRateSpread.lowLabel }}</small>
                <small>最高 {{ channelRateSpread.highLabel }}</small>
              </div>
            </article>
          </section>

          <section v-for="group in previewPlatformGroups" :key="group.key" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <article v-for="row in group.items" :key="row.id" class="embedded-platform-card">
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
                    <el-button
                      :icon="Refresh"
                      :loading="monitoringPlatformId === row.id"
                      circle
                      title="采集"
                      @click="runMonitor(row)"
                    />
                    <el-button :icon="Edit" circle title="编辑" @click="openEdit(row)" />
                    <el-button :icon="Delete" circle plain title="删除" type="danger" @click="remove(row)" />
                  </div>
                </div>
              </header>

              <div class="embedded-platform-body">
                <div class="embedded-platform-metrics">
                  <div class="timestamp">
                    <span>最后采集</span>
                    <strong>{{ formatTime(row.checked_at) }}</strong>
                  </div>
                  <div>
                    <span>平台余额</span>
                    <strong>{{ formatMoney(row.balance) }}</strong>
                  </div>
                  <div>
                    <span>今日消耗</span>
                    <strong>{{ formatUsagePair(row.today_quota_used, row.today_actual_used) }}</strong>
                  </div>
                  <div>
                    <span>累计消耗</span>
                    <strong>{{ formatUsagePair(row.quota_used, actualUsage(row, row.quota_used)) }}</strong>
                  </div>
                  <div>
                    <span>额度上限</span>
                    <strong>{{ formatMoney(row.quota_limit) }}</strong>
                  </div>
                  <div>
                    <span>连接耗时</span>
                    <strong>{{ formatLatency(row.connect_latency_ms) }}</strong>
                  </div>
                  <div>
                    <span>首 token</span>
                    <strong>{{ formatLatency(row.model_first_token_ms) }}</strong>
                  </div>
                </div>
                <div v-if="row.model_test_error" class="embedded-account-error">
                  模型测试失败（{{ row.model_test_model || '未配置模型' }}）：{{ row.model_test_error }}
                </div>
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
                          <span><em>账号</em>{{ accountDisplayLabel(account) }}</span>
                          <span v-if="accountLoginLabel(account)">
                            <em>登录</em>{{ accountLoginLabel(account) }}
                          </span>
                          <span>
                            <em>代理</em>{{ accountProxyLabel(account) }}
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
                          <span>今日</span>
                          <strong>{{ formatUsagePair(account.today_quota_used, account.today_actual_used) }}</strong>
                        </div>
                        <div>
                          <span>消耗</span>
                          <strong>{{ formatUsagePair(account.quota_used, actualUsage(row, account.quota_used)) }}</strong>
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

                <div class="embedded-group-rate-panel">
                  <div class="embedded-section-label">接口分组速览</div>
                  <div
                    v-if="overviewDiscoveredGroupRates(row.discovered_group_rates).length > 0"
                    class="embedded-group-rate-list overview-group-rate-list"
                  >
                    <div
                      v-for="groupRate in overviewDiscoveredGroupRates(row.discovered_group_rates)"
                      :key="groupRate.external_group_id"
                      class="embedded-group-rate-row"
                      :class="{ highlighted: groupRate.is_configured }"
                    >
                      <div class="embedded-group-rate-main">
                        <div class="embedded-group-rate-title">
                          <strong>{{ groupRate.name }}</strong>
                          <div class="embedded-group-rate-tags">
                            <el-tag v-if="groupRate.is_highest" size="small" type="success" effect="light">
                              最高
                            </el-tag>
                            <el-tag v-if="groupRate.is_lowest" size="small" type="info" effect="light">
                              最低
                            </el-tag>
                            <el-tag v-if="groupRate.is_configured" size="small" type="warning" effect="light">
                              监控
                            </el-tag>
                          </div>
                        </div>
                        <span>{{ groupRate.external_group_id }}</span>
                        <span v-if="groupRate.description" class="embedded-group-rate-desc">
                          {{ groupRate.description }}
                        </span>
                      </div>
                      <div class="embedded-group-rate-values">
                        <div>
                          <span>原始倍率</span>
                          <strong>{{ formatMultiplier(groupRate.rate_multiplier) }}</strong>
                        </div>
                        <div>
                          <span>实际倍率</span>
                          <strong>{{ formatMultiplier(groupRate.effective_rate_multiplier) }}</strong>
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
                            <el-tag v-if="channel.is_highest" size="small" type="success" effect="light">
                              最高
                            </el-tag>
                            <el-tag v-if="channel.is_lowest" size="small" type="info" effect="light">
                              最低
                            </el-tag>
                            <el-tag v-if="channel.status" size="small" type="info" effect="light">
                              {{ channel.status }}
                            </el-tag>
                          </div>
                        </div>
                        <span>渠道 {{ channel.external_channel_id }}</span>
                        <span v-if="channel.base_url" class="embedded-group-rate-desc">
                          {{ channel.base_url }}
                        </span>
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
          </section>
          <el-empty v-if="!loading && platforms.length === 0" description="暂无平台" />
        </div>

        <div v-else-if="activeEmbeddedView === 'balances'" class="embedded-panel-list">
          <section v-for="group in previewPlatformGroups" :key="`balances-${group.key}`" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <article v-for="row in group.items" :key="row.id" class="embedded-trends-section">
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
          </section>
        </div>

        <div v-else-if="activeEmbeddedView === 'firstTokens'" class="embedded-panel-list">
          <section v-for="group in previewPlatformGroups" :key="`first-tokens-${group.key}`" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <article v-for="row in group.items" :key="row.id" class="embedded-trends-section embedded-rate-section">
              <div class="embedded-platform-title compact embedded-rate-header">
                <div>
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.model_test_model ? `测试模型：${row.model_test_model}` : '未配置测试模型' }}</span>
                </div>
                <span>最近 7 天首 token</span>
              </div>
              <div v-if="platformFirstTokenHistory[row.id]" class="embedded-rate-platform-card">
                <FirstTokenLineChart :series="platformFirstTokenHistory[row.id]" />
                <div class="history-axis rate-history-axis">
                  <span>{{ platformFirstTokenFirstDate(row.id) }}</span>
                  <span>首 token 趋势 / 当前 {{ formatLatency(row.model_first_token_ms) }}</span>
                  <span>{{ platformFirstTokenLastDate(row.id) }}</span>
                </div>
              </div>
              <div v-else class="embedded-empty">暂无首 token 趋势</div>
            </article>
          </section>
        </div>

        <div v-else-if="activeEmbeddedView === 'rates'" class="embedded-panel-list">
          <section v-for="group in previewPlatformGroups" :key="`rates-${group.key}`" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <article v-for="row in group.items" :key="row.id" class="embedded-trends-section embedded-rate-section">
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
          </section>
        </div>

        <div v-else-if="activeEmbeddedView === 'groupRates'" class="embedded-panel-list">
          <section v-for="group in previewPlatformGroups" :key="`group-rates-${group.key}`" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <el-collapse v-model="collapsedGroupRatePanels" class="embedded-group-rate-collapse">
              <el-collapse-item v-for="row in group.items" :key="row.id" :name="row.id">
                <template #title>
                  <div class="embedded-group-rate-collapse-title">
                    <div class="embedded-platform-title compact">
                      <strong>{{ row.name }}</strong>
                      <span>{{ row.base_url }}</span>
                    </div>
                    <div class="platform-badges">
                      <el-tag size="small" effect="plain">{{ providerLabel(row.provider_type) }}</el-tag>
                      <el-tag size="small" effect="light" type="info">{{ siteStrategyLabel(row) }}</el-tag>
                      <el-tag size="small" effect="light" type="success">
                        {{ uniqueDiscoveredGroupRates(row.discovered_group_rates).length }} 个分组
                      </el-tag>
                    </div>
                    <el-button
                      :icon="Refresh"
                      :loading="monitoring"
                      size="small"
                      @click.stop="runGroupRatePanelMonitor(row)"
                    >
                      {{ row.provider_type === 'newapi' ? '立即采集' : '采集倍率' }}
                    </el-button>
                  </div>
                </template>
                <div class="embedded-group-rate-page">
                  <div
                    v-if="uniqueDiscoveredGroupRates(row.discovered_group_rates).length > 0"
                    class="embedded-group-rate-list"
                  >
                    <div
                      v-for="groupRate in uniqueDiscoveredGroupRates(row.discovered_group_rates)"
                      :key="groupRate.external_group_id"
                      class="embedded-group-rate-row"
                      :class="{ highlighted: groupRate.is_configured }"
                    >
                      <div class="embedded-group-rate-main">
                        <div class="embedded-group-rate-title">
                          <strong>{{ groupRate.name }}</strong>
                          <div class="embedded-group-rate-tags">
                            <el-tag v-if="groupRate.is_configured" size="small" type="warning" effect="light">
                              监控
                            </el-tag>
                            <el-tag v-if="groupRate.last_error" size="small" type="danger" effect="light">
                              异常
                            </el-tag>
                          </div>
                        </div>
                        <span>{{ groupRate.external_group_id }}</span>
                        <span v-if="groupRate.description" class="embedded-group-rate-desc">
                          {{ groupRate.description }}
                        </span>
                      </div>
                      <div class="embedded-group-rate-values">
                        <div>
                          <span>原始倍率</span>
                          <strong>{{ formatMultiplier(groupRate.rate_multiplier) }}</strong>
                        </div>
                        <div>
                          <span>实际倍率</span>
                          <strong>{{ formatMultiplier(groupRate.effective_rate_multiplier) }}</strong>
                        </div>
                        <div>
                          <span>RPM</span>
                          <strong>{{ groupRate.rpm_limit ?? '-' }}</strong>
                        </div>
                        <div>
                          <span>最后采集</span>
                          <strong>{{ formatTime(groupRate.checked_at) }}</strong>
                        </div>
                      </div>
                      <div v-if="groupRate.last_error" class="embedded-account-error">
                        {{ groupRate.last_error }}
                      </div>
                    </div>
                  </div>
                  <div v-else class="embedded-empty">暂无分组倍率</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </section>
        </div>

        <div v-else-if="activeEmbeddedView === 'notifications'" class="embedded-panel-list">
          <section class="embedded-provider-group">
            <div class="embedded-section-label">邮件通知</div>
            <article class="embedded-platform-card notification-card">
              <header class="embedded-platform-header">
                <div class="embedded-platform-title">
                  <div>
                    <strong>SMTP 发信配置</strong>
                    <span>只配置发信服务器和发件人，收件人在下方单独管理</span>
                  </div>
                </div>
                <div class="embedded-platform-controls">
                  <el-button :loading="savingNotification" type="primary" @click="saveNotification()">保存配置</el-button>
                </div>
              </header>

              <el-form class="notification-form notification-form-grid" :model="notificationForm" label-position="top">
                <el-form-item label="SMTP 主机">
                  <el-input v-model="notificationForm.smtp_host" placeholder="smtp.qq.com" />
                </el-form-item>
                <el-form-item label="SMTP 端口">
                  <el-input-number v-model="notificationForm.smtp_port" :min="1" :max="65535" class="full-width" controls-position="right" />
                </el-form-item>
                <el-form-item label="SMTP 用户">
                  <el-input v-model="notificationForm.smtp_username" placeholder="3097553108@qq.com" />
                </el-form-item>
                <el-form-item label="SMTP 密码">
                  <el-input
                    v-model="notificationForm.smtp_password"
                    :placeholder="notificationSetting?.has_smtp_password ? '留空则不修改已有密码' : '请输入 SMTP 授权码'"
                    show-password
                    type="password"
                  />
                  <div v-if="notificationSetting?.has_smtp_password" class="form-help">密码已配置，留空会保留当前值。</div>
                </el-form-item>
                <el-form-item label="发件人邮箱">
                  <el-input v-model="notificationForm.from_email" placeholder="3097553108@qq.com" />
                </el-form-item>
                <el-form-item label="发件人名称">
                  <el-input v-model="notificationForm.from_name" placeholder="Sub2API" />
                </el-form-item>
              </el-form>

              <div class="notification-switches">
                <div class="notification-switch-item">
                  <div>
                    <strong>启用通知</strong>
                    <span>邮件通知总开关，关闭后所有功能项都不会发送邮件</span>
                  </div>
                  <el-switch v-model="notificationForm.enabled" />
                </div>
                <div class="notification-switch-item">
                  <div>
                    <strong>使用 SSL</strong>
                    <span>QQ 邮箱 465 端口建议开启 SSL</span>
                  </div>
                  <el-switch v-model="notificationForm.smtp_use_ssl" />
                </div>
                <div class="notification-switch-item">
                  <div>
                    <strong>使用 STARTTLS</strong>
                    <span>587 端口通常使用 STARTTLS，不能和 SSL 同时启用</span>
                  </div>
                  <el-switch v-model="notificationForm.smtp_use_tls" :disabled="notificationForm.smtp_use_ssl" />
                </div>
              </div>

              <div class="notification-feature-list">
                <div class="notification-feature-heading">
                  <strong>通知功能项</strong>
                  <span>单独控制哪些业务事件可以发送邮件</span>
                </div>
                <div class="notification-feature-item">
                  <div>
                    <strong>分组变化通知</strong>
                    <span>平台分组倍率变化、接口分组新增或减少时发送邮件</span>
                  </div>
                  <el-switch v-model="notificationForm.notify_group_rate_changes" :disabled="!notificationForm.enabled" />
                </div>
                <div class="notification-feature-item">
                  <div>
                    <strong>额度不足提醒</strong>
                    <span>预留功能项，后续接入余额阈值后生效</span>
                  </div>
                  <el-switch v-model="notificationForm.notify_low_balance" :disabled="!notificationForm.enabled" />
                </div>
              </div>

              <div class="notification-status">
                <el-tag :type="notificationForm.enabled ? 'success' : 'info'" effect="light">
                  {{ notificationForm.enabled ? '已启用' : '未启用' }}
                </el-tag>
                <span>最近测试：{{ formatTime(notificationSetting?.last_tested_at ?? null) }}</span>
              </div>
            </article>

            <article class="embedded-platform-card notification-card">
              <header class="embedded-platform-header">
                <div class="embedded-platform-title">
                  <div>
                    <strong>收件人</strong>
                    <span>分组变化通知会发送给所有启用的收件人</span>
                  </div>
                </div>
              </header>

              <div class="notification-recipient-editor">
                <el-input v-model="recipientForm.name" placeholder="名称，例如 运维" />
                <el-input v-model="recipientForm.email" placeholder="邮箱，例如 ops@example.com" />
                <el-switch v-model="recipientForm.enabled" />
                <el-button :icon="Plus" type="primary" @click="saveRecipient">添加</el-button>
              </div>

              <el-table :data="notificationRecipients" size="small">
                <el-table-column prop="name" label="名称" min-width="140" />
                <el-table-column prop="email" label="邮箱" min-width="220" />
                <el-table-column label="启用" width="90">
                  <template #default="{ row }">
                    <el-switch :model-value="row.enabled" @change="toggleRecipient(row)" />
                  </template>
                </el-table-column>
                <el-table-column label="最近测试" width="170">
                  <template #default="{ row }">{{ formatTime(row.last_tested_at) }}</template>
                </el-table-column>
                <el-table-column prop="last_error" label="错误" min-width="180" show-overflow-tooltip />
                <el-table-column label="操作" width="150">
                  <template #default="{ row }">
                    <el-button :loading="testingNotification" link @click="testRecipient(row)">测试</el-button>
                    <el-button link type="danger" @click="removeRecipient(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </article>
          </section>
        </div>

        <div v-else class="embedded-panel-list">
          <section v-for="group in previewPlatformGroups" :key="`settings-${group.key}`" class="embedded-provider-group">
            <div class="embedded-section-label">{{ group.label }}</div>
            <article v-for="row in group.items" :key="row.id" class="embedded-platform-card">
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
          </section>
        </div>
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
        <el-form-item label="测试模型">
          <el-input v-model="form.model_test_model" placeholder="例如 gpt-4o-mini；留空则不测试首 token" />
          <div class="form-help">采集时会按站点地址调用 /v1/chat/completions，记录流式首 token 响应时间。</div>
        </el-form-item>
        <el-form-item
          :label="form.provider_type === 'newapi' ? '采集 Cron' : '余额 Cron'"
          prop="balance_cron"
        >
          <el-input
            v-model="form.balance_cron"
            placeholder="*/10 * * * *"
            @input="syncNewApiCron"
          />
        </el-form-item>
        <el-form-item v-if="form.provider_type !== 'newapi'" label="倍率 Cron" prop="rate_cron">
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
        <el-form-item label="额度提醒阈值">
          <el-input-number
            v-model="form.low_balance_threshold"
            :min="0"
            :precision="6"
            :step="1"
            class="full-width"
            placeholder="留空则不提醒"
          />
          <div class="form-help">平台汇总余额低于该值时触发邮件提醒，最多连续发送 3 次。</div>
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

    <el-dialog v-model="errorDialogVisible" title="异常明细" width="860px">
      <div v-if="errorSummaryItems.length > 0" class="error-summary-list">
        <article v-for="item in errorSummaryItems" :key="item.key" class="error-summary-item">
          <div class="error-summary-head">
            <div>
              <strong>{{ item.platformName }}</strong>
              <span>{{ item.source }}</span>
            </div>
            <div class="error-summary-actions">
              <el-tag size="small" type="danger" effect="light">{{ item.providerLabel }}</el-tag>
              <el-button
                :icon="Delete"
                :loading="clearingErrorKey === item.key"
                link
                size="small"
                type="danger"
                @click="clearError(item)"
              >
                删除
              </el-button>
            </div>
          </div>
          <pre>{{ item.message }}</pre>
          <div class="error-summary-meta">
            <span>{{ item.target }}</span>
            <span>{{ formatTime(item.checkedAt) }}</span>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无异常明细" />
      <template #footer>
        <el-button @click="errorDialogVisible = false">关闭</el-button>
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
            <el-table-column label="账号标识" min-width="160">
              <template #default="{ row }">{{ accountDisplayLabel(row) }}</template>
            </el-table-column>
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
            <el-table-column label="已消耗" min-width="150">
              <template #default="{ row }">{{ formatUsagePair(row.quota_used, actualUsage(detail, row.quota_used)) }}</template>
            </el-table-column>
            <el-table-column label="额度上限" width="120">
              <template #default="{ row }">{{ formatMoney(row.quota_limit) }}</template>
            </el-table-column>
            <el-table-column label="最后采集" width="170">
              <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
            </el-table-column>
            <el-table-column label="最近代理" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ accountProxyLabel(row) }}</template>
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
              <p>配置指定分组，New API 通用策略填写 codex 即读取 group_ratio.codex。</p>
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
        <el-button
          v-if="detail?.provider_type === 'newapi'"
          :icon="Refresh"
          :loading="monitoring"
          type="primary"
          @click="runDetailMonitor"
        >
          立即采集
        </el-button>
        <template v-else>
          <el-button :icon="Refresh" :loading="monitoring" @click="runDetailBalanceMonitor">采集余额</el-button>
          <el-button :icon="Refresh" :loading="monitoring" type="primary" @click="runDetailRateMonitor">采集倍率</el-button>
        </template>
      </template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" :title="accountEditing ? '编辑账号余额监控' : '添加账号余额监控'" width="520px">
      <el-form :model="accountForm" label-width="110px">
        <el-form-item label="显示名称">
          <el-input v-model="accountForm.name" />
        </el-form-item>
        <el-form-item label="平台账号 ID">
          <el-input v-model="accountForm.external_account_id" placeholder="可留空，New API 登录后自动获取用户 ID" />
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import BalanceLineChart from '@/components/BalanceLineChart.vue'
import FirstTokenLineChart from '@/components/FirstTokenLineChart.vue'
import RateLineChart from '@/components/RateLineChart.vue'
import {
  clearPlatformError,
  createAccountMonitor,
  createGroupMonitor,
  createNotificationRecipient,
  createPlatform,
  deleteAccountMonitor,
  deleteGroupMonitor,
  deleteNotificationRecipient,
  deletePlatform,
  fetchDashboard,
  fetchEmbeddedHistories,
  fetchNotificationSetting,
  fetchNotificationRecipients,
  fetchPlatform,
  fetchPlatformDetails,
  fetchProviders,
  fetchSiteStrategies,
  runPlatformBalanceMonitor,
  runPlatformMonitor,
  runPlatformRateMonitor,
  testNotificationRecipient,
  updateAccountMonitor,
  updateNotificationRecipient,
  updateNotificationSetting,
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
  type NotificationRecipient,
  type NotificationRecipientPayload,
  type NotificationSetting,
  type NotificationSettingPayload,
  type PlatformFirstTokenHistorySeries,
  type PlatformDetail,
  type PlatformPayload,
  type PlatformStatus,
  type ProviderOption,
  type RelayPlatform,
  type SiteStrategyOption,
} from '@/api/client'

const route = useRoute()
const providers = ref<ProviderOption[]>([])
const siteStrategies = ref<SiteStrategyOption[]>([])
const platforms = ref<PlatformDetail[]>([])
const stats = ref<DashboardStats | null>(null)
const detail = ref<PlatformDetail | null>(null)
const platformBalanceHistory = ref<Record<number, AccountBalanceHistorySeries[]>>({})
const platformRateHistory = ref<Record<number, GroupRateHistorySeries[]>>({})
const platformFirstTokenHistory = ref<Record<number, PlatformFirstTokenHistorySeries>>({})
const embeddedHistoriesLoaded = ref(false)
const embeddedHistoriesLoading = ref(false)
const notificationSetting = ref<NotificationSetting | null>(null)
const notificationRecipients = ref<NotificationRecipient[]>([])
const loading = ref(false)
const saving = ref(false)
const monitoring = ref(false)
const monitoringPlatformId = ref<number | null>(null)
const savingNotification = ref(false)
const testingNotification = ref(false)
const dialogVisible = ref(false)
const errorDialogVisible = ref(false)
const clearingErrorKey = ref<string | null>(null)
const detailVisible = ref(false)
const accountDialogVisible = ref(false)
const groupDialogVisible = ref(false)
const editing = ref<RelayPlatform | null>(null)
const accountEditing = ref<AccountMonitor | null>(null)
const formRef = ref<FormInstance>()
const collapsedGroupRatePanels = ref<Array<number | string>>([])
type EmbeddedViewKey = 'overview' | 'balances' | 'firstTokens' | 'rates' | 'groupRates' | 'notifications' | 'settings'

const embeddedViewKeys: EmbeddedViewKey[] = ['overview', 'balances', 'firstTokens', 'rates', 'groupRates', 'notifications', 'settings']
const activeEmbeddedView = computed<EmbeddedViewKey>(() => {
  const value = route.query.view
  if (typeof value === 'string' && embeddedViewKeys.includes(value as EmbeddedViewKey)) {
    return value as EmbeddedViewKey
  }
  return 'overview'
})
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
    key: 'firstTokens',
    label: '首 token 趋势',
    description: '按平台查看模型首 token 网络状态',
  },
  {
    key: 'rates',
    label: '倍率趋势',
    description: '按平台展示分组趋势',
  },
  {
    key: 'groupRates',
    label: '分组倍率',
    description: '按平台查看全部分组倍率',
  },
  {
    key: 'notifications',
    label: '邮件通知',
    description: '分组变化 SMTP 告警',
  },
  {
    key: 'settings',
    label: '监控配置',
    description: '账号、分组和采集任务入口',
  },
] as const

type EmbeddedMenuItem = (typeof embeddedMenuItems)[number]

const embeddedView = computed(
  () => embeddedMenuItems.find((item) => item.key === activeEmbeddedView.value) ?? embeddedMenuItems[0],
)
const embeddedViewTitle = computed(() => embeddedView.value.label)
const embeddedViewDescription = computed(() => embeddedView.value.description)
const previewPlatformGroups = computed(() => {
  const newapi = platforms.value.filter((row) => row.provider_type === 'newapi')
  const sub2api = platforms.value.filter((row) => row.provider_type === 'sub2api')
  const others = platforms.value.filter((row) => row.provider_type !== 'newapi' && row.provider_type !== 'sub2api')
  return [
    { key: 'newapi', label: 'newapi', items: newapi },
    { key: 'sub2api', label: 'sub2api', items: sub2api },
    { key: 'other', label: '其他', items: others },
  ].filter((group) => group.items.length > 0)
})
const errorSummaryItems = computed(() => {
  return platforms.value.flatMap((platform) => platformErrorSummaryItems(platform))
})
const downOrDegradedCount = computed(() => (stats.value?.degraded_platforms ?? 0) + (stats.value?.down_platforms ?? 0))
const monitoredAccountRows = computed(() => {
  return platforms.value.flatMap((platform) =>
    platform.account_monitors.map((account) => ({ platform, account })),
  )
})
const enabledPlatformCount = computed(() => platforms.value.filter((row) => row.enabled).length)
const topSpendingPlatform = computed(() => {
  return platforms.value
    .filter((row) => row.today_actual_used !== null || row.today_quota_used !== null)
    .slice()
    .sort((a, b) => (b.today_actual_used ?? b.today_quota_used ?? 0) - (a.today_actual_used ?? a.today_quota_used ?? 0))[0] ?? null
})
const lowestBalanceAccount = computed(() => {
  return monitoredAccountRows.value
    .filter((row) => row.account.enabled && row.account.balance !== null)
    .slice()
    .sort((a, b) => (a.account.balance ?? 0) - (b.account.balance ?? 0))[0] ?? null
})
const totalAccountBalance = computed(() => {
  const values = monitoredAccountRows.value
    .map((row) => row.account.balance)
    .filter((value): value is number => value !== null)
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null
})
const totalAccountTodayUsed = computed(() => {
  const values = monitoredAccountRows.value
    .map((row) => row.account.today_quota_used)
    .filter((value): value is number => value !== null)
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null
})
const totalAccountTodayActualUsed = computed(() => {
  const values = monitoredAccountRows.value
    .map((row) => row.account.today_actual_used)
    .filter((value): value is number => value !== null)
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null
})
const lowBalanceAccountCount = computed(() => {
  return monitoredAccountRows.value.filter((row) => {
    const threshold = row.platform.low_balance_threshold
    return row.account.enabled && threshold !== null && row.account.balance !== null && row.account.balance <= threshold
  }).length
})

type RateSpread = {
  spread: number | null
  lowLabel: string
  highLabel: string
}

const groupRateSpread = computed<RateSpread>(() => {
  const rows = platforms.value.flatMap((platform) =>
    uniqueDiscoveredGroupRates(platform.discovered_group_rates)
      .filter((rate) => rate.effective_rate_multiplier !== null)
      .map((rate) => ({ platform, rate, value: rate.effective_rate_multiplier as number })),
  )
  return buildRateSpread(rows, (row) => `${row.platform.name} / ${row.rate.name}`)
})
const channelRateSpread = computed<RateSpread>(() => {
  const rows = platforms.value.flatMap((platform) =>
    uniqueDiscoveredChannelRates(platform.discovered_channel_rates)
      .filter((rate) => rate.rate_multiplier !== null)
      .map((rate) => ({ platform, rate, value: rate.rate_multiplier as number })),
  )
  return buildRateSpread(rows, (row) => `${row.platform.name} / ${row.rate.name}`)
})
const overviewKpis = computed(() => [
  {
    key: 'platforms',
    label: '平台',
    value: `${stats.value?.enabled_platforms ?? enabledPlatformCount.value} / ${stats.value?.total_platforms ?? platforms.value.length}`,
    detail: `${stats.value?.healthy_platforms ?? 0} 健康，${downOrDegradedCount.value} 异常`,
    tone: downOrDegradedCount.value > 0 ? 'warn' : 'ok',
  },
  {
    key: 'accounts',
    label: '账号监控',
    value: String(stats.value?.account_monitor_count ?? monitoredAccountRows.value.length),
    detail: `余额合计 ${formatMoney(totalAccountBalance.value)}`,
    tone: lowBalanceAccountCount.value > 0 ? 'warn' : 'neutral',
  },
  {
    key: 'spend',
    label: '账号今日消耗',
    value: formatUsagePair(totalAccountTodayUsed.value, totalAccountTodayActualUsed.value),
    detail: `总计 ${formatUsagePair(stats.value?.today_quota_used ?? null, stats.value?.today_actual_used ?? null)}`,
    tone: 'neutral',
  },
  {
    key: 'risk',
    label: '余额风险',
    value: String(lowBalanceAccountCount.value),
    detail: lowestBalanceAccount.value
      ? `${lowestBalanceAccount.value.platform.name} / ${lowestBalanceAccount.value.account.name}`
      : '暂无触发阈值',
    tone: lowBalanceAccountCount.value > 0 ? 'bad' : 'ok',
  },
  {
    key: 'groups',
    label: '分组监控',
    value: String(stats.value?.group_monitor_count ?? '-'),
    detail: `倍率差 ${formatMultiplier(groupRateSpread.value.spread)}`,
    tone: groupRateSpread.value.spread !== null && groupRateSpread.value.spread > 1 ? 'warn' : 'neutral',
  },
  {
    key: 'latency',
    label: '平均连接',
    value: formatLatency(stats.value?.average_connect_latency_ms ?? null),
    detail: `首 token ${formatLatency(stats.value?.average_model_first_token_ms ?? null)}`,
    tone:
      stats.value?.average_connect_latency_ms !== null &&
      stats.value?.average_connect_latency_ms !== undefined &&
      stats.value.average_connect_latency_ms >= 1000
        ? 'warn'
        : 'neutral',
  },
])

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
  low_balance_threshold: null,
  model_test_model: null,
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

const notificationForm = reactive<NotificationSettingPayload>({
  enabled: false,
  smtp_host: null,
  smtp_port: 587,
  smtp_username: null,
  smtp_password: null,
  smtp_use_ssl: false,
  smtp_use_tls: true,
  from_email: null,
  from_name: null,
  notify_group_rate_changes: true,
  notify_low_balance: false,
})

const recipientForm = reactive<NotificationRecipientPayload>({
  name: '',
  email: '',
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
    low_balance_threshold: null,
    model_test_model: null,
  })
}

function onProviderTypeChange(value: string | number | boolean | undefined) {
  if (value === 'newapi') {
    form.auth_header_name = 'Authorization'
    form.auth_header_prefix = 'Bearer'
    form.rate_cron = form.balance_cron
    return
  }
  if (!form.auth_header_prefix) {
    form.auth_header_prefix = 'Bearer'
  }
}

function syncNewApiCron() {
  if (form.provider_type === 'newapi') {
    form.rate_cron = form.balance_cron
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
    low_balance_threshold: row.low_balance_threshold,
    model_test_model: row.model_test_model,
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
    const [providerRows, siteStrategyRows, dashboard, details, notification, recipients] = await Promise.all([
      fetchProviders(),
      fetchSiteStrategies(),
      fetchDashboard(),
      fetchPlatformDetails(),
      fetchNotificationSetting(),
      fetchNotificationRecipients(),
    ])
    providers.value = providerRows
    siteStrategies.value = siteStrategyRows
    stats.value = dashboard
    platforms.value = details
    embeddedHistoriesLoaded.value = false
    notificationSetting.value = notification
    notificationRecipients.value = recipients
    syncNotificationForm(notification)
    void ensureEmbeddedHistoriesLoaded()
  } finally {
    loading.value = false
  }
}

function syncNotificationForm(setting: NotificationSetting) {
  Object.assign(notificationForm, {
    enabled: setting.enabled,
    smtp_host: setting.smtp_host,
    smtp_port: setting.smtp_port,
    smtp_username: setting.smtp_username,
    smtp_password: null,
    smtp_use_ssl: setting.smtp_use_ssl,
    smtp_use_tls: setting.smtp_use_tls,
    from_email: setting.from_email,
    from_name: setting.from_name,
    notify_group_rate_changes: setting.notify_group_rate_changes,
    notify_low_balance: setting.notify_low_balance,
  })
}

async function saveNotification(showError = true) {
  savingNotification.value = true
  try {
    const payload = { ...notificationForm }
    if (payload.smtp_use_ssl) {
      payload.smtp_use_tls = false
    }
    if (!payload.smtp_password) {
      delete payload.smtp_password
    }
    const saved = await updateNotificationSetting(payload)
    notificationSetting.value = saved
    syncNotificationForm(saved)
    ElMessage.success('通知配置已保存')
    return saved
  } catch (error) {
    if (showError) {
      await showNotificationError('保存通知配置失败', error)
    }
    throw error
  } finally {
    savingNotification.value = false
  }
}

function resetRecipientForm() {
  Object.assign(recipientForm, { name: '', email: '', enabled: true })
}

async function saveRecipient() {
  if (!recipientForm.name || !recipientForm.email) {
    ElMessage.error('请填写收件人名称和邮箱')
    return
  }
  await createNotificationRecipient(recipientForm)
  resetRecipientForm()
  notificationRecipients.value = await fetchNotificationRecipients()
  ElMessage.success('收件人已添加')
}

async function toggleRecipient(row: NotificationRecipient) {
  await updateNotificationRecipient(row.id, { enabled: !row.enabled })
  notificationRecipients.value = await fetchNotificationRecipients()
}

async function removeRecipient(row: NotificationRecipient) {
  await ElMessageBox.confirm(`确认删除收件人「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteNotificationRecipient(row.id)
  notificationRecipients.value = await fetchNotificationRecipients()
  ElMessage.success('已删除收件人')
}

async function testRecipient(row: NotificationRecipient) {
  testingNotification.value = true
  try {
    await saveNotification(false)
    await testNotificationRecipient(row.id)
    ElMessage.success(`测试邮件已发送给 ${row.email}`)
    const [latestSetting, latestRecipients] = await Promise.all([
      fetchNotificationSetting(),
      fetchNotificationRecipients(),
    ])
    notificationSetting.value = latestSetting
    notificationRecipients.value = latestRecipients
    syncNotificationForm(latestSetting)
  } catch (error) {
    const [latestSetting, latestRecipients] = await Promise.all([
      fetchNotificationSetting(),
      fetchNotificationRecipients(),
    ])
    notificationSetting.value = latestSetting
    notificationRecipients.value = latestRecipients
    syncNotificationForm(latestSetting)
    await showNotificationError('测试邮件发送失败', error)
  } finally {
    testingNotification.value = false
  }
}

function notificationErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (typeof item === 'object' && item !== null && 'msg' in item) {
            const msg = (item as { msg?: unknown }).msg
            return typeof msg === 'string' ? msg : ''
          }
          return ''
        })
        .filter(Boolean)
        .join('\n')
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return '操作失败，请检查 SMTP 配置和收件人设置。'
}

async function showNotificationError(title: string, error: unknown) {
  await ElMessageBox.alert(notificationErrorMessage(error), title, {
    type: 'error',
    confirmButtonText: '知道了',
  })
}

async function reloadDetail() {
  if (!detail.value) {
    return
  }
  detail.value = await fetchPlatform(detail.value.id)
}

async function refreshPlatformState(platformId: number, refreshHistories = false) {
  const [refreshedPlatform, dashboard] = await Promise.all([fetchPlatform(platformId), fetchDashboard()])
  platforms.value = platforms.value.map((row) => (row.id === platformId ? refreshedPlatform : row))
  stats.value = dashboard
  if (detail.value?.id === platformId) {
    detail.value = refreshedPlatform
  }
  if (refreshHistories && detail.value?.id === platformId) {
    await loadEmbeddedHistories([platformId])
  }
}

async function loadEmbeddedHistories(platformIds: number[]) {
  const histories = await fetchEmbeddedHistories(platformIds)
  platformBalanceHistory.value = histories.balances
  platformRateHistory.value = histories.rates
  platformFirstTokenHistory.value = histories.first_tokens
  embeddedHistoriesLoaded.value = true
}

function historyViewNeedsData(view: EmbeddedViewKey) {
  return view === 'balances' || view === 'firstTokens' || view === 'rates'
}

async function ensureEmbeddedHistoriesLoaded() {
  if (embeddedHistoriesLoaded.value || embeddedHistoriesLoading.value || !historyViewNeedsData(activeEmbeddedView.value)) {
    return
  }
  embeddedHistoriesLoading.value = true
  try {
    await loadEmbeddedHistories(platforms.value.map((row) => row.id))
  } finally {
    embeddedHistoriesLoading.value = false
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
    if (payload.provider_type === 'newapi') {
      payload.rate_cron = payload.balance_cron
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

async function clearError(item: ErrorSummaryItem) {
  clearingErrorKey.value = item.key
  try {
    await clearPlatformError(item.sourceType, item.targetId)
    ElMessage.success('异常信息已删除')
    await load()
  } finally {
    clearingErrorKey.value = null
  }
}

async function runMonitor(row: RelayPlatform) {
  monitoringPlatformId.value = row.id
  try {
    await runPlatformMonitor(row.id)
    ElMessage.success('采集完成')
    await refreshPlatformState(row.id)
  } finally {
    monitoringPlatformId.value = null
  }
}

async function runAllEnabledMonitors() {
  const targets = platforms.value.filter((row) => row.enabled)
  if (targets.length === 0) {
    ElMessage.info('暂无启用平台')
    return
  }
  monitoring.value = true
  try {
    for (const row of targets) {
      monitoringPlatformId.value = row.id
      await runPlatformMonitor(row.id)
    }
    ElMessage.success(`已完成 ${targets.length} 个平台采集`)
    await load()
  } finally {
    monitoringPlatformId.value = null
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
    await refreshPlatformState(detail.value.id, true)
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
    await refreshPlatformState(detail.value.id, true)
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
    await refreshPlatformState(detail.value.id, true)
  } finally {
    monitoring.value = false
  }
}

async function runGroupRatePanelMonitor(row: RelayPlatform) {
  if (row.provider_type === 'newapi') {
    await runMonitor(row)
    return
  }
  await runDetailRateMonitorFor(row)
}

async function runDetailRateMonitorFor(row: RelayPlatform) {
  monitoring.value = true
  try {
    await runPlatformRateMonitor(row.id)
    ElMessage.success('倍率采集完成')
    await refreshPlatformState(row.id)
  } finally {
    monitoring.value = false
  }
}

async function saveAccount() {
  if (!detail.value || !accountForm.name) {
    ElMessage.error('请填写账号名称')
    return
  }
  const isNewApiAccount = detail.value.provider_type === 'newapi'
  if (isNewApiAccount && !accountForm.username) {
    ElMessage.error('请填写登录账号')
    return
  }
  if (!isNewApiAccount && !accountForm.external_account_id && !accountForm.username) {
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

function accountDisplayLabel(account: AccountMonitor) {
  return account.username || account.external_account_id || '-'
}

function accountProxyLabel(account: AccountMonitor) {
  return account.last_proxy_url || '直连'
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

function actualUsage(row: Pick<RelayPlatform, 'effective_rate_factor'> | null, value: number | null) {
  if (value === null || !row || row.effective_rate_factor === null) {
    return null
  }
  return value * row.effective_rate_factor
}

function formatUsagePair(platformValue: number | null, actualValue: number | null) {
  return `${formatMoney(platformValue)} / ${formatMoney(actualValue)}`
}

function formatMultiplier(value: number | null) {
  if (value === null) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatLatency(value: number | null) {
  if (value === null) {
    return '-'
  }
  if (value >= 1000) {
    return `${Number((value / 1000).toFixed(2))}s`
  }
  return `${Math.round(value)}ms`
}

function buildRateSpread<T extends { value: number }>(rows: T[], label: (row: T) => string): RateSpread {
  if (rows.length === 0) {
    return { spread: null, lowLabel: '-', highLabel: '-' }
  }
  const sorted = rows.slice().sort((a, b) => a.value - b.value)
  const low = sorted[0]
  const high = sorted[sorted.length - 1]
  return {
    spread: high.value - low.value,
    lowLabel: `${formatMultiplier(low.value)} ${label(low)}`,
    highLabel: `${formatMultiplier(high.value)} ${label(high)}`,
  }
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

function platformFirstTokenFirstDate(platformId: number) {
  return firstDateLabel(platformFirstTokenHistory.value[platformId]?.points[0]?.at)
}

function platformFirstTokenLastDate(platformId: number) {
  const series = platformFirstTokenHistory.value[platformId]
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

type ErrorSummaryItem = {
  key: string
  sourceType: string
  targetId: number
  platformName: string
  providerLabel: string
  source: string
  target: string
  message: string
  checkedAt: string | null
}

function platformErrorSummaryItems(platform: PlatformDetail): ErrorSummaryItem[] {
  const provider = providerLabel(platform.provider_type)
  const items: ErrorSummaryItem[] = []
  if (platform.last_error) {
    items.push({
      key: `platform:${platform.id}`,
      sourceType: 'platform',
      targetId: platform.id,
      platformName: platform.name,
      providerLabel: provider,
      source: '平台',
      target: platform.base_url,
      message: platform.last_error,
      checkedAt: platform.checked_at,
    })
  }
  for (const account of platform.account_monitors) {
    if (!account.last_error) continue
    items.push({
      key: `account:${account.id}`,
      sourceType: 'account',
      targetId: account.id,
      platformName: platform.name,
      providerLabel: provider,
      source: '账号余额',
      target: `${account.name} / ${accountDisplayLabel(account)}`,
      message: account.last_error,
      checkedAt: account.checked_at,
    })
  }
  for (const group of platform.group_monitors) {
    if (!group.last_error) continue
    items.push({
      key: `group:${group.id}`,
      sourceType: 'group',
      targetId: group.id,
      platformName: platform.name,
      providerLabel: provider,
      source: '监控分组',
      target: `${group.name} / ${group.external_group_id}`,
      message: group.last_error,
      checkedAt: group.checked_at,
    })
  }
  for (const groupRate of uniqueDiscoveredGroupRates(platform.discovered_group_rates)) {
    if (!groupRate.last_error) continue
    items.push({
      key: `discovered-group:${groupRate.id}`,
      sourceType: 'discovered_group',
      targetId: groupRate.id,
      platformName: platform.name,
      providerLabel: provider,
      source: '发现分组',
      target: `${groupRate.name} / ${groupRate.external_group_id}`,
      message: groupRate.last_error,
      checkedAt: groupRate.checked_at,
    })
  }
  for (const channel of uniqueDiscoveredChannelRates(platform.discovered_channel_rates)) {
    if (!channel.last_error) continue
    items.push({
      key: `channel:${channel.id}`,
      sourceType: 'channel',
      targetId: channel.id,
      platformName: platform.name,
      providerLabel: provider,
      source: '渠道倍率',
      target: `${channel.name} / ${channel.external_channel_id}`,
      message: channel.last_error,
      checkedAt: channel.checked_at,
    })
  }
  return items
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

watch(activeEmbeddedView, () => {
  void ensureEmbeddedHistoriesLoaded()
})
</script>

