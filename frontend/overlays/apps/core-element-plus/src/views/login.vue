<script setup lang="ts">
import { ElMessage } from 'element-plus'
import ColorScheme from '@/layouts/components/Topbar/Toolbar/ColorScheme/index.vue'

defineOptions({ name: 'Login' })

const route = useRoute()
const router = useRouter()
const appAccountStore = useAppAccountStore()
const appSettingsStore = useAppSettingsStore()
const apiKey = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await appAccountStore.loginWithApiKey(apiKey.value)
    ElMessage.success('Workspace connected')
    const redirect = route.query.redirect?.toString() || appSettingsStore.settings.app.home.fullPath
    await router.replace(redirect)
  }
  catch {
    ElMessage.error('API Key is invalid or the API is unreachable')
  }
  finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="bg-banner" />
  <div class="text-base p-1 border rounded-lg bg-background right-4 top-4 absolute z-1">
    <ColorScheme v-if="appSettingsStore.settings.toolbar.colorScheme" />
  </div>
  <div class="login-box">
    <div class="login-banner">
      <div class="p-10 relative z-1 h-full flex flex-col justify-between">
        <div>
          <div class="text-sm text-muted-foreground tracking-widest uppercase">Amazon Geographic Intelligence</div>
          <h1 class="text-4xl tracking-tight font-semibold mt-4">Geo Rank Monitor</h1>
          <p class="text-muted-foreground mt-4 max-w-md">
            Observe Amazon organic rank across IP regions and Deliver-to ZIP codes,
            then calculate a weighted national rank.
          </p>
        </div>
        <div class="text-xs text-muted-foreground">Fantastic Admin · Element Plus UI foundation</div>
      </div>
    </div>
    <div class="login-form flex-col-center">
      <div class="w-full max-w-sm px-8">
        <div class="text-2xl font-semibold mb-2">Connect workspace</div>
        <div class="text-sm text-muted-foreground mb-6">
          Enter a Workspace API Key. It is stored only in this browser.
        </div>
        <el-form @submit.prevent="submit">
          <el-form-item>
            <el-input
              v-model="apiKey"
              size="large"
              type="password"
              show-password
              autocomplete="off"
              placeholder="agrm_..."
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submit">
            Connect
          </el-button>
        </el-form>
        <el-alert
          class="mt-6"
          type="info"
          :closable="false"
          title="Need a key?"
          description="Bootstrap the first workspace with agrm-bootstrap, or create another key from the API Keys page."
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.bg-banner {
  position: fixed;
  inset: 0;
  background:
    radial-gradient(circle at 20% 20%, oklch(var(--primary) / 18%), transparent 40%),
    radial-gradient(circle at 80% 80%, oklch(var(--border) / 50%), transparent 42%);
}
.login-box {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  width: min(980px, calc(100% - 32px));
  min-height: 560px;
  overflow: hidden;
  border: 1px solid oklch(var(--border));
  border-radius: 18px;
  background: oklch(var(--background));
  transform: translate(-50%, -50%);
  box-shadow: 0 24px 80px rgb(0 0 0 / 12%);
}
.login-banner {
  position: relative;
  width: 52%;
  background: oklch(var(--muted));
  overflow: hidden;
}
.login-banner::after {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 70% 30%, oklch(var(--primary) / 28%), transparent 45%);
  content: "";
}
.login-form { width: 48%; }
@media (max-width: 760px) {
  .login-box { position: relative; top: auto; left: auto; margin: 70px 16px 20px; width: auto; min-height: 0; transform: none; }
  .login-banner { display: none; }
  .login-form { width: 100%; min-height: 480px; }
}
</style>
