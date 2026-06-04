<template>
  <el-container class="app-shell">
    <el-aside class="sidebar" width="232px">
      <div class="brand">
        <div class="brand-mark">S2</div>
        <div>
          <div class="brand-title">Sub2 Monitor</div>
          <div class="brand-subtitle">Relay platform status</div>
        </div>
      </div>
      <el-menu default-active="/" router class="nav-menu">
        <el-menu-item index="/">
          <el-icon><Monitor /></el-icon>
          <span>平台监控</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>中转平台服务数据</h1>
          <p>监控为 sub2api 提供密钥的平台状态、额度、延迟和可用性。</p>
        </div>
        <div class="account">
          <span>{{ auth.user?.username }}</span>
          <el-button :icon="SwitchButton" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { Monitor, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function handleLogout() {
  await auth.logout()
  ElMessage.success('已退出登录')
  await router.replace({ name: 'login' })
}
</script>

