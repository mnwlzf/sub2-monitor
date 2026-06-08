<template>
  <el-container class="app-shell">
    <el-container class="main-panel">
      <el-header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageSubtitle }}</p>
        </div>
      </el-header>
      <el-main class="content">
        <section class="embedded-workspace">
          <aside class="embedded-menu">
            <div class="embedded-menu-brand">
              <strong>Sub2 Monitor</strong>
              <span>功能菜单</span>
            </div>
            <button
              v-for="item in menuItems"
              :key="item.key"
              :class="{ active: isActive(item) }"
              type="button"
              @click="openMenuItem(item)"
            >
              <span>{{ item.label }}</span>
              <small>{{ item.description }}</small>
            </button>
          </aside>

          <router-view />
        </section>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const menuItems = [
  {
    key: 'overview',
    label: '平台总览',
    description: '状态、账号余额和采集操作',
    route: { name: 'platforms', query: { view: 'overview' } },
  },
  {
    key: 'balances',
    label: '余额趋势',
    description: '账号余额按 cron 间隔变化',
    route: { name: 'platforms', query: { view: 'balances' } },
  },
  {
    key: 'rates',
    label: '倍率趋势',
    description: '按平台展示分组趋势',
    route: { name: 'platforms', query: { view: 'rates' } },
  },
  {
    key: 'groupRates',
    label: '分组倍率',
    description: '按平台查看全部分组倍率',
    route: { name: 'platforms', query: { view: 'groupRates' } },
  },
  {
    key: 'notifications',
    label: '邮件通知',
    description: '分组变化 SMTP 告警',
    route: { name: 'platforms', query: { view: 'notifications' } },
  },
  {
    key: 'settings',
    label: '监控配置',
    description: '账号、分组和采集任务入口',
    route: { name: 'platforms', query: { view: 'settings' } },
  },
  {
    key: 'sub2apiDatabase',
    label: 'Sub2API 数据库',
    description: '连接状态、SQL 日志和权重同步',
    route: { name: 'sub2api-database' },
  },
] as const

type MenuItem = (typeof menuItems)[number]

const pageTitle = computed(() => {
  if (route.name === 'sub2api-database') {
    return 'Sub2API 数据库'
  }
  return '平台监控'
})
const pageSubtitle = computed(() => {
  if (route.name === 'sub2api-database') {
    return '查看目标数据库连接状态与修改审计'
  }
  return '跟踪中转平台余额、倍率和账号状态'
})

const activePlatformView = computed(() => {
  const value = route.query.view
  return typeof value === 'string' && value ? value : 'overview'
})

function isActive(item: MenuItem) {
  if (item.key === 'sub2apiDatabase') {
    return route.name === 'sub2api-database'
  }
  return route.name === 'platforms' && activePlatformView.value === item.key
}

function openMenuItem(item: MenuItem) {
  router.push(item.route)
}
</script>
