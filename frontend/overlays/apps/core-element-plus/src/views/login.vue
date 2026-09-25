<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi } from '@/api/agrm'
import ColorScheme from '@/layouts/components/Topbar/Toolbar/ColorScheme/index.vue'

defineOptions({ name: 'Login' })

type Mode = 'login' | 'register' | 'forgot' | 'api'

const route = useRoute()
const router = useRouter()
const appAccountStore = useAppAccountStore()
const appSettingsStore = useAppSettingsStore()
const inviteToken = computed(() => route.query.invite?.toString() || '')
const mode = ref<Mode>(inviteToken.value ? 'register' : 'login')
const email = ref('')
const password = ref('')
const displayName = ref('')
const workspaceName = ref('')
const apiKey = ref('')
const loading = ref(false)
const mfaChallengeToken = ref('')
const mfaCode = ref('')
const rememberDevice = ref(false)

async function finish(result?: { workspace?: { mfa_setup_required?: boolean } }) {
  ElMessage.success(inviteToken.value ? 'Workspace joined' : 'Signed in')
  if (result?.workspace?.mfa_setup_required) {
    ElMessage.warning('This workspace requires MFA. Complete setup to continue.')
    await router.replace('/workspace/security')
    return
  }
  const redirect = route.query.redirect?.toString() || appSettingsStore.settings.app.home.fullPath
  await router.replace(redirect)
}

async function submitLogin() {
  loading.value = true
  try {
    const result = await appAccountStore.loginWithCredentials(email.value, password.value)
    if (result.mfa_required) {
      mfaChallengeToken.value = result.challenge_token
      mfaCode.value = ''
      return
    }
    if (inviteToken.value) {
      const accepted = await agrmApi.acceptInvitation(inviteToken.value)
      appAccountStore.applySession(accepted)
      await finish(accepted)
      return
    }
    await finish(result)
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Email or password is invalid')
  }
  finally {
    loading.value = false
  }
}

async function submitMfa() {
  if (!mfaCode.value.trim()) {
    ElMessage.warning('Enter your authenticator or recovery code')
    return
  }
  loading.value = true
  try {
    await appAccountStore.completeMfa(
      mfaChallengeToken.value,
      mfaCode.value.trim(),
      rememberDevice.value,
    )
    if (inviteToken.value) {
      const accepted = await agrmApi.acceptInvitation(inviteToken.value)
      appAccountStore.applySession(accepted)
      mfaChallengeToken.value = ''
      await finish(accepted)
      return
    }
    mfaChallengeToken.value = ''
    await finish()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Invalid MFA code')
  }
  finally {
    loading.value = false
  }
}

function cancelMfa() {
  mfaChallengeToken.value = ''
  mfaCode.value = ''
  rememberDevice.value = false
  password.value = ''
}

async function submitRegister() {
  loading.value = true
  try {
    const result = await appAccountStore.registerAccount({
      email: email.value,
      password: password.value,
      display_name: displayName.value,
      ...(inviteToken.value
        ? { invitation_token: inviteToken.value }
        : { workspace_name: workspaceName.value }),
    })
    await finish(result)
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Unable to create account')
  }
  finally {
    loading.value = false
  }
}

async function submitForgot() {
  if (!email.value.trim()) {
    ElMessage.warning('Email is required')
    return
  }
  loading.value = true
  try {
    const result = await agrmApi.forgotPassword(email.value.trim())
    ElMessage.success(result.message)
    mode.value = 'login'
  }
  catch {
    ElMessage.success('If the account exists, a password reset email will be sent.')
    mode.value = 'login'
  }
  finally {
    loading.value = false
  }
}

async function submitApiKey() {
  loading.value = true
  try {
    await appAccountStore.loginWithApiKey(apiKey.value)
    ElMessage.success('Legacy workspace connected')
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
        <div class="text-xs text-muted-foreground">Secure workspace accounts · API keys remain available for automation</div>
      </div>
    </div>

    <div class="login-form flex-col-center">
      <div class="w-full max-w-sm px-8 py-8">
        <el-alert
          v-if="inviteToken"
          type="success"
          :closable="false"
          class="mb-5"
          title="Workspace invitation"
          description="Create an account with the invited email, or sign in if you already have one."
        />

        <el-segmented
          v-model="mode"
          :options="[
            { label: 'Sign in', value: 'login' },
            { label: 'Create account', value: 'register' },
            { label: 'Recover', value: 'forgot' },
            { label: 'API Key', value: 'api' },
          ]"
          class="w-full mb-6"
        />

        <template v-if="mode === 'login'">
          <template v-if="mfaChallengeToken">
            <div class="text-2xl font-semibold mb-2">Two-factor authentication</div>
            <div class="text-sm text-muted-foreground mb-6">
              Enter the 6-digit code from your authenticator app, or use one recovery code.
            </div>
            <el-form label-position="top" @submit.prevent="submitMfa">
              <el-form-item label="Authentication code">
                <el-input
                  v-model="mfaCode"
                  size="large"
                  autocomplete="one-time-code"
                  placeholder="123456 or XXXX-XXXX-XXXX"
                  @keyup.enter="submitMfa"
                />
              </el-form-item>
              <el-checkbox v-model="rememberDevice" class="mb-4">
                Trust this device
              </el-checkbox>
              <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submitMfa">
                Verify and sign in
              </el-button>
              <el-button class="w-full mt-2" text @click="cancelMfa">
                Use another account
              </el-button>
            </el-form>
          </template>
          <template v-else>
            <div class="text-2xl font-semibold mb-2">Welcome back</div>
            <div class="text-sm text-muted-foreground mb-6">
              Sign in with your workspace account.
            </div>
            <el-form label-position="top" @submit.prevent="submitLogin">
              <el-form-item label="Email">
                <el-input v-model="email" size="large" autocomplete="email" placeholder="you@company.com" />
              </el-form-item>
              <el-form-item label="Password">
                <el-input
                  v-model="password"
                  size="large"
                  type="password"
                  show-password
                  autocomplete="current-password"
                  @keyup.enter="submitLogin"
                />
              </el-form-item>
              <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submitLogin">
                Sign in
              </el-button>
              <el-button class="w-full mt-2" text @click="mode = 'forgot'">
                Forgot password?
              </el-button>
            </el-form>
          </template>
        </template>

        <template v-else-if="mode === 'register'">
          <div class="text-2xl font-semibold mb-2">{{ inviteToken ? 'Join workspace' : 'Create workspace' }}</div>
          <div class="text-sm text-muted-foreground mb-6">
            {{ inviteToken ? 'Create your user account to accept the invitation.' : 'Create the first Owner account for a new workspace.' }}
          </div>
          <el-form label-position="top" @submit.prevent="submitRegister">
            <el-form-item label="Name">
              <el-input v-model="displayName" size="large" autocomplete="name" placeholder="Your name" />
            </el-form-item>
            <el-form-item label="Email">
              <el-input v-model="email" size="large" autocomplete="email" placeholder="you@company.com" />
            </el-form-item>
            <el-form-item v-if="!inviteToken" label="Workspace">
              <el-input v-model="workspaceName" size="large" placeholder="Acme Commerce" />
            </el-form-item>
            <el-form-item label="Password">
              <el-input
                v-model="password"
                size="large"
                type="password"
                show-password
                autocomplete="new-password"
                placeholder="At least 10 characters"
                @keyup.enter="submitRegister"
              />
            </el-form-item>
            <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submitRegister">
              {{ inviteToken ? 'Create account & join' : 'Create account' }}
            </el-button>
          </el-form>
        </template>

        <template v-else-if="mode === 'forgot'">
          <div class="text-2xl font-semibold mb-2">Recover account</div>
          <div class="text-sm text-muted-foreground mb-6">
            Enter your email. If an account exists, we will send a single-use reset link.
          </div>
          <el-form label-position="top" @submit.prevent="submitForgot">
            <el-form-item label="Email">
              <el-input
                v-model="email"
                size="large"
                autocomplete="email"
                placeholder="you@company.com"
                @keyup.enter="submitForgot"
              />
            </el-form-item>
            <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submitForgot">
              Send reset link
            </el-button>
            <el-button class="w-full mt-2" text @click="mode = 'login'">
              Back to sign in
            </el-button>
          </el-form>
        </template>

        <template v-else>
          <div class="text-2xl font-semibold mb-2">Legacy API Key</div>
          <div class="text-sm text-muted-foreground mb-6">
            Use this only for an existing API-key-only workspace. Human accounts are recommended for the web console.
          </div>
          <el-form @submit.prevent="submitApiKey">
            <el-form-item>
              <el-input
                v-model="apiKey"
                size="large"
                type="password"
                show-password
                autocomplete="off"
                placeholder="agrm_..."
                @keyup.enter="submitApiKey"
              />
            </el-form-item>
            <el-button class="w-full" size="large" type="primary" :loading="loading" @click="submitApiKey">
              Connect legacy workspace
            </el-button>
          </el-form>
          <el-alert
            class="mt-6"
            type="info"
            :closable="false"
            title="Migrating an existing workspace?"
            description="Use an admin API key to bootstrap the first human Owner, then sign in with email and password."
          />
        </template>
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
  min-height: 620px;
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
  .login-form { width: 100%; min-height: 560px; }
}
</style>
