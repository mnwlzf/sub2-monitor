import { defineStore } from 'pinia'

import { fetchMe, login, logout, type UserInfo } from '@/api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as UserInfo | null,
    initialized: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user),
  },
  actions: {
    async initialize() {
      if (this.initialized) {
        return
      }
      try {
        const session = await fetchMe()
        this.user = session.user
      } catch {
        this.user = null
      } finally {
        this.initialized = true
      }
    },
    async login(username: string, password: string) {
      const session = await login(username, password)
      this.user = session.user
      this.initialized = true
    },
    async logout() {
      await logout()
      this.user = null
      this.initialized = true
    },
  },
})

