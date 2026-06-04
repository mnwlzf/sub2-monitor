<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-copy">
        <div class="brand-line">
          <span class="brand-mark">S2</span>
          <span>Sub2 Monitor</span>
        </div>
        <h1>中转平台监控</h1>
        <p>登录后查看为 sub2api 提供密钥的平台服务数据。</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @submit.prevent="submit">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            autocomplete="username"
            placeholder="用户名"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            autocomplete="current-password"
            placeholder="密码"
            show-password
            size="large"
            type="password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button :loading="loading" native-type="submit" size="large" type="primary" class="login-button">
          登录
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  username: 'admin',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  await formRef.value?.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch {
    ElMessage.error('用户名或密码不正确')
  } finally {
    loading.value = false
  }
}
</script>

