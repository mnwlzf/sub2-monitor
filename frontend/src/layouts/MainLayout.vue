<template>
  <el-container :class="['app-shell', { 'embedded-shell': isEmbedded }]">
    <el-aside v-if="!isEmbedded" class="sidebar" width="232px">
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
      <el-header v-if="!isEmbedded" class="topbar">
        <div>
          <h1>中转平台服务数据</h1>
          <p>监控为 sub2api 提供密钥的平台状态、额度、延迟和可用性。</p>
        </div>
      </el-header>
      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { Monitor } from '@element-plus/icons-vue'
import { ref } from 'vue'

function detectEmbedded() {
  try {
    return window.self !== window.top || new URLSearchParams(window.location.search).has('embedded')
  } catch {
    return true
  }
}

const isEmbedded = ref(detectEmbedded())
</script>
