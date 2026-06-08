import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'
import PlatformsView from '@/views/PlatformsView.vue'
import Sub2APIDatabaseView from '@/views/Sub2APIDatabaseView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: MainLayout,
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

export default router
