<template>
  <el-container class="app-shell">
    <el-aside class="sidebar" width="220px">
      <div class="brand">
        <span class="brand-mark">S2</span>
        <div>
          <div class="brand-title">Sub2 Monitor</div>
          <div class="brand-subtitle">运维控制台</div>
        </div>
      </div>
      <el-menu :default-active="activePath" class="nav-menu" router>
        <el-menu-item index="/">
          <el-icon><Monitor /></el-icon>
          <span>平台监控</span>
        </el-menu-item>
        <el-menu-item index="/sub2api-database">
          <el-icon><DataAnalysis /></el-icon>
          <span>Sub2API 数据库</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageSubtitle }}</p>
        </div>
      </el-header>
      <nav class="mobile-nav">
        <RouterLink to="/">平台监控</RouterLink>
        <RouterLink to="/sub2api-database">Sub2API 数据库</RouterLink>
      </nav>
      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { DataAnalysis, Monitor } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const activePath = computed(() => (route.path === '/sub2api-database' ? route.path : '/'))
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
</script>
