import type { SessionResult } from '@/api/agrm'
import { agrmApi } from '@/api/agrm'
import router from '@/router'

export const useAppAccountStore = defineStore('appAccount', () => {
  const appSettingsStore = useAppSettingsStore()
  const appTabbarStore = useAppTabbarStore()
  const appRouteStore = useAppRouteStore()
  const appMenuStore = useAppMenuStore()

  const storedToken = localStorage.getItem('token') ?? ''
  if (storedToken.startsWith('agrs_')) {
    localStorage.removeItem('token')
  }

  const token = ref(storedToken.startsWith('agrm_') ? storedToken : '')
  const authMode = ref(localStorage.getItem('authMode') ?? (token.value ? 'api' : ''))
  const account = ref(localStorage.getItem('account') ?? '')
  const avatar = ref('')
  const permissions = ref<string[]>(['*'])
  const isLogin = computed(() => authMode.value === 'session' || Boolean(token.value))

  function applySession(result: SessionResult) {
    localStorage.removeItem('token')
    token.value = ''
    authMode.value = 'session'
    localStorage.setItem('authMode', 'session')
    account.value = result.user.display_name || result.user.email
    localStorage.setItem('account', account.value)
    permissions.value = [result.workspace.role]
  }

  function clearAuth() {
    localStorage.removeItem('token')
    localStorage.removeItem('authMode')
    token.value = ''
    authMode.value = ''
  }

  async function loginWithCredentials(email: string, password: string) {
    clearAuth()
    const result = await agrmApi.loginAccount({ email, password })
    applySession(result)
    return result
  }

  async function registerAccount(payload: {
    email: string
    password: string
    display_name: string
    workspace_name?: string
    invitation_token?: string
  }) {
    clearAuth()
    const result = await agrmApi.registerAccount(payload)
    applySession(result)
    return result
  }

  async function loginWithApiKey(apiKey: string) {
    const normalized = apiKey.trim()
    if (!normalized) {
      throw new Error('API Key is required')
    }
    clearAuth()
    token.value = normalized
    authMode.value = 'api'
    localStorage.setItem('token', normalized)
    localStorage.setItem('authMode', 'api')
    try {
      await agrmApi.validateKey()
      account.value = 'Legacy API workspace'
      localStorage.setItem('account', account.value)
      permissions.value = ['*']
    }
    catch (error) {
      clearAuth()
      throw error
    }
  }

  async function login(data: { account: string, password: string }) {
    await loginWithCredentials(data.account, data.password)
  }

  function logout(redirect = router.currentRoute.value.fullPath) {
    if (authMode.value === 'session') {
      void agrmApi.logoutAccount().catch(() => undefined)
    }
    clearAuth()
    router.push({
      name: 'login',
      query: {
        ...(redirect !== appSettingsStore.settings.app.home.fullPath
          && router.currentRoute.value.name !== 'login' && { redirect }),
      },
    }).then(logoutCleanStatus)
  }

  function requestLogout() {
    logout()
  }

  function logoutCleanStatus() {
    localStorage.removeItem('account')
    account.value = ''
    permissions.value = ['*']
    appSettingsStore.updateSettings({}, true)
    appTabbarStore.clean()
    appRouteStore.removeRoutes()
    appMenuStore.setActived(0)
  }

  async function getPermissions() {
    if (authMode.value === 'api' && token.value) {
      permissions.value = ['*']
      return
    }
    if (authMode.value !== 'session') {
      permissions.value = []
      return
    }
    try {
      const profile = await agrmApi.getMe()
      account.value = profile.user.display_name || profile.user.email
      localStorage.setItem('account', account.value)
      permissions.value = [profile.workspace.role]
    }
    catch (error) {
      clearAuth()
      throw error
    }
  }

  async function editPassword(data: { password: string, newPassword: string }) {
    if (authMode.value !== 'session') {
      throw new Error('Human session required')
    }
    await agrmApi.changePassword(data.password, data.newPassword)
  }

  return {
    token,
    authMode,
    account,
    avatar,
    permissions,
    isLogin,
    login,
    loginWithCredentials,
    registerAccount,
    loginWithApiKey,
    applySession,
    logout,
    requestLogout,
    getPermissions,
    editPassword,
  }
})
