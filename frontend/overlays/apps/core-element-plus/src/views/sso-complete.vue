<script setup lang="ts">
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'SsoComplete' })

const router = useRouter()
const appAccountStore = useAppAccountStore()
const appSettingsStore = useAppSettingsStore()
const failed = ref(false)

onMounted(async () => {
  try {
    const profile = await agrmApi.getMe()
    appAccountStore.applyProfile(profile)
    if (
      profile.workspace.mfa_setup_required
      || profile.workspace.mfa_session_verification_required
    ) {
      await router.replace('/workspace/security')
      return
    }
    await router.replace(appSettingsStore.settings.app.home.fullPath)
  }
  catch {
    failed.value = true
    setTimeout(() => {
      void router.replace({ name: 'login', query: { sso: 'failed' } })
    }, 1200)
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-6">
    <el-card class="w-full max-w-md" shadow="never">
      <el-result
        v-if="failed"
        icon="error"
        title="SSO sign-in failed"
        sub-title="Returning to sign in…"
      />
      <div v-else class="text-center space-y-4 py-8">
        <el-icon class="is-loading text-3xl"><Loading /></el-icon>
        <div class="text-xl font-semibold">Completing secure sign-in</div>
        <p class="text-sm text-muted-foreground">
          Verifying your workspace session…
        </p>
      </div>
    </el-card>
  </div>
</template>
