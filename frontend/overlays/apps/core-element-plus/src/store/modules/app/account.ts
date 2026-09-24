import type { SessionResult } from '@/api/agrm'
import { agrmApi } from '@/api/agrm'
import router from '@/router'

export const useAppAccountStore = defineStore('appAccount', () => {
  const appSettingsStore = useAppSettingsStore()
  const appTabbarStore = useAppTabbarStore()
  const appRouteStore = useAppRouteStore()
  const appMenuStore = useAppMenuStore()

  const token = ref(localStorage.getItem('token') ?? '')
  const account = ref(localStorage.getItem('account') ?? '')
  const avatar = ref('')
  const permissions = ref<string[]>(['*'])
  const isLogin = computed(() => Boolean(token.value))

  function applySession(result: SessionResult) {
    token.value = result.session_token
    localStorage.setItem('token', result.session_token)
    account.value = result.user.display_name || result.user.email
    localStorage.setItem('account', account.value)
    permissions.value = [result.workspace.role]
  }

  function clearToken() {
    localStorage.removeItem('token')
    token.value = ''
  }

  async function loginWithCredentials(email: string, password: string) {
    clearToken()
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
    clearToken()
    const result = await agrmApi.registerAccount(payload)
    applySession(result)
    return result
  }

  async function loginWithApiKey(apiKey: string) {
    const normalized = apiKey.trim()
    if (!normalized) {
      throw new Error('API Key is required')
    }
    token.value = normalized
    localStorage.setItem('token', normalized)
    try {
      await agrmApi.validateKey()
      account.value = 'Legacy API workspace'
      localStorage.setItem('account', account.value)
      permissions.value = ['*']
    }
    catch (error) {
      clearToken()
      throw error
    }
  }

  async function login(data: { account: string, password: string }) {
    await loginWithCredentials(data.account, data.password)
  }

  function logout(redirect = router.currentRoute.value.fullPath) {
    if (token.value.startsWith('agrs_')) {
      void agrmApi.logoutAccount().catch(() => undefined)
    }
    clearToken()
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
    if (!token.value) {
      permissions.value = []
      return
    }
    if (!token.value.startsWith('agrs_')) {
      permissions.value = ['*']
      return
    }
    const profile = await agrmApi.getMe()
    account.value = profile.user.display_name || profile.user.email
    localStorage.setItem('account', account.value)
    permissions.value = [profile.workspace.role]
  }

  async function editPassword(_data: { password: string, newPassword: string }) {
    throw new Error('Password change is not enabled yet')
  }

  return {
    token,
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
