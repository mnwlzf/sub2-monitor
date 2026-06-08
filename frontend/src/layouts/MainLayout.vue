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
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

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
