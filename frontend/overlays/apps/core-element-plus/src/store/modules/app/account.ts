import { agrmApi } from '@/api/agrm'
import router from '@/router'

export const useAppAccountStore = defineStore('appAccount', () => {
  const appSettingsStore = useAppSettingsStore()
  const appTabbarStore = useAppTabbarStore()
  const appRouteStore = useAppRouteStore()
  const appMenuStore = useAppMenuStore()

  const token = ref(localStorage.getItem('token') ?? '')
  const account = ref(localStorage.getItem('account') ?? 'Workspace')
  const avatar = ref('')
  const permissions = ref<string[]>(['*'])
  const isLogin = computed(() => Boolean(token.value))

  async function loginWithApiKey(apiKey: string) {
    const normalized = apiKey.trim()
    if (!normalized) {
      throw new Error('API Key is required')
    }
    token.value = normalized
    localStorage.setItem('token', normalized)
    try {
      await agrmApi.validateKey()
      account.value = 'Workspace'
      localStorage.setItem('account', 'Workspace')
    }
    catch (error) {
      localStorage.removeItem('token')
      token.value = ''
      throw error
    }
  }

  async function login(data: { account: string, password: string }) {
    await loginWithApiKey(data.password || data.account)
  }

  function logout(redirect = router.currentRoute.value.fullPath) {
    localStorage.removeItem('token')
    token.value = ''
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
    permissions.value = ['*']
  }

  async function editPassword() {
    throw new Error('Password authentication is not enabled for this deployment')
  }

  return {
    token,
    account,
    avatar,
    permissions,
    isLogin,
    login,
    loginWithApiKey,
    logout,
    requestLogout,
    getPermissions,
    editPassword,
  }
})
