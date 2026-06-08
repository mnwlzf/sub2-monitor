import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'
import LoginView from '@/views/LoginView.vue'
import PlatformsView from '@/views/PlatformsView.vue'
import Sub2APIDatabaseView from '@/views/Sub2APIDatabaseView.vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/',
      component: MainLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'platforms',
          component: PlatformsView,
        },
        {
          path: 'sub2api-database',
          name: 'sub2api-database',
          component: Sub2APIDatabaseView,
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return '/'
  }
  return true
})

export default router
