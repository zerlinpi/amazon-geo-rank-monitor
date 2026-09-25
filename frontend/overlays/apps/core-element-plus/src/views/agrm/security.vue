<script setup lang="ts">
import type {
  AccountProfile,
  AuthSecurityEvent,
  MfaEnrollmentResult,
  UserSession,
} from '@/api/agrm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'AccountSecurity' })

const appAccountStore = useAppAccountStore()
const loading = ref(false)
const sessions = ref<UserSession[]>([])
const securityEvents = ref<AuthSecurityEvent[]>([])
const profile = ref<AccountProfile>()
const currentPassword = ref('')
const newPassword = ref('')
const changing = ref(false)

const enrollment = ref<MfaEnrollmentResult>()
const enrollmentDialog = ref(false)
const enrollmentCode = ref('')
const confirmingMfa = ref(false)
const recoveryCodes = ref<string[]>([])
const recoveryDialog = ref(false)

const disableDialog = ref(false)
const disablePassword = ref('')
const disableCode = ref('')
const disablingMfa = ref(false)
const sessionMfaCode = ref('')
const verifyingSessionMfa = ref(false)

const isHuman = computed(() => appAccountStore.authMode === 'session')
const mfaEnabled = computed(() => profile.value?.user.mfa_enabled === true)

async function load() {
  if (!isHuman.value) {
    sessions.value = []
    return
  }
  loading.value = true
  try {
    const [sessionResult, eventResult, profileResult] = await Promise.all([
      agrmApi.getSessions(),
      agrmApi.getSecurityEvents(100),
      agrmApi.getMe(),
    ])
    sessions.value = sessionResult
    securityEvents.value = eventResult
    profile.value = profileResult
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load account security')
  }
  finally {
    loading.value = false
  }
}

async function resendVerification() {
  try {
    const result = await agrmApi.resendVerification()
    if (result.sent) {
      ElMessage.success('Verification email sent')
    }
    else {
      ElMessage.info('Email is already verified')
    }
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to send verification email')
  }
}

async function beginMfa() {
  try {
    enrollment.value = await agrmApi.beginMfaEnrollment()
    enrollmentCode.value = ''
    enrollmentDialog.value = true
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Unable to start MFA setup')
  }
}

async function confirmMfa() {
  if (!enrollmentCode.value.trim()) {
    ElMessage.warning('Enter the 6-digit authenticator code')
    return
  }
  confirmingMfa.value = true
  try {
    const result = await agrmApi.confirmMfaEnrollment(enrollmentCode.value.trim())
    recoveryCodes.value = result.recovery_codes
    enrollmentDialog.value = false
    recoveryDialog.value = true
    ElMessage.success('Two-factor authentication enabled')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Invalid authenticator code')
  }
  finally {
    confirmingMfa.value = false
  }
}

async function copyText(value: string, message: string) {
  await navigator.clipboard.writeText(value)
  ElMessage.success(message)
}

async function copyRecoveryCodes() {
  await copyText(recoveryCodes.value.join('\n'), 'Recovery codes copied')
}

async function regenerateRecoveryCodes() {
  try {
    const { value } = await ElMessageBox.prompt(
      'Enter a current authenticator code or unused recovery code.',
      'Regenerate recovery codes',
      {
        inputPlaceholder: '123456 or XXXX-XXXX-XXXX',
        confirmButtonText: 'Regenerate',
      },
    )
    const result = await agrmApi.regenerateRecoveryCodes(value)
    recoveryCodes.value = result.recovery_codes
    recoveryDialog.value = true
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Unable to regenerate recovery codes')
  }
}

async function disableMfa() {
  if (!disablePassword.value || !disableCode.value.trim()) {
    ElMessage.warning('Password and MFA code are required')
    return
  }
  disablingMfa.value = true
  try {
    await agrmApi.disableMfa(disablePassword.value, disableCode.value.trim())
    disableDialog.value = false
    disablePassword.value = ''
    disableCode.value = ''
    ElMessage.success('Two-factor authentication disabled')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Unable to disable MFA')
  }
  finally {
    disablingMfa.value = false
  }
}

async function verifySessionMfa() {
  if (!sessionMfaCode.value.trim()) {
    ElMessage.warning('Enter your authenticator or recovery code')
    return
  }
  verifyingSessionMfa.value = true
  try {
    await agrmApi.verifyCurrentSessionMfa(sessionMfaCode.value.trim())
    sessionMfaCode.value = ''
    ElMessage.success('Current session verified with MFA')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Invalid MFA code')
  }
  finally {
    verifyingSessionMfa.value = false
  }
}

async function revoke(row: UserSession) {
  if (row.current) {
    return
  }
  try {
    await ElMessageBox.confirm(
      'Revoke this device session? It will need to sign in again.',
      'Revoke session',
      { type: 'warning', confirmButtonText: 'Revoke' },
    )
    await agrmApi.revokeSession(row.id)
    ElMessage.success('Session revoked')
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to revoke session')
  }
}

async function changePassword() {
  if (!currentPassword.value || newPassword.value.length < 10) {
    ElMessage.warning('Enter your current password and a new password of at least 10 characters')
    return
  }
  changing.value = true
  try {
    const result = await agrmApi.changePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    ElMessage.success(`Password changed · ${result.revoked_other_sessions} other session(s) revoked`)
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to change password')
  }
  finally {
    changing.value = false
  }
}

async function logoutAll() {
  try {
    await ElMessageBox.confirm(
      'Sign out every active device and revoke trusted-device bypasses?',
      'Sign out everywhere',
      { type: 'warning', confirmButtonText: 'Sign out all' },
    )
    await agrmApi.logoutAll()
    appAccountStore.logout()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to sign out all sessions')
  }
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">Account</div>
      <h1 class="text-2xl font-semibold mt-1">Security</h1>
      <p class="text-sm text-muted-foreground mt-1">
        Manage email verification, MFA, password and active browser sessions.
      </p>
    </div>

    <el-alert
      v-if="!isHuman"
      type="info"
      :closable="false"
      title="Human account required"
      description="Account security controls are unavailable while connected with a Legacy API Key."
    />

    <template v-else>
      <el-alert
        v-if="profile?.workspace.mfa_setup_required"
        type="warning"
        :closable="false"
        title="This workspace requires MFA"
        description="Enable two-factor authentication below before accessing workspace resources."
      />

      <el-card
        v-if="profile?.workspace.mfa_session_verification_required"
        shadow="never"
      >
        <template #header>
          <span class="font-medium">Verify this SSO session with MFA</span>
        </template>
        <p class="text-sm text-muted-foreground mb-4">
          Your identity provider did not assert MFA for this sign-in. Complete local TOTP verification to access this workspace.
        </p>
        <div class="max-w-md flex gap-2">
          <el-input
            v-model="sessionMfaCode"
            autocomplete="one-time-code"
            placeholder="123456 or XXXX-XXXX-XXXX"
            @keyup.enter="verifySessionMfa"
          />
          <el-button
            type="primary"
            :loading="verifyingSessionMfa"
            @click="verifySessionMfa"
          >
            Verify
          </el-button>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span class="font-medium">Email verification</span>
        </template>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="text-sm">{{ profile?.user.email || '—' }}</div>
            <div class="text-xs text-muted-foreground mt-1">
              {{ profile?.user.email_verified ? 'Verified' : 'Verification pending' }}
            </div>
          </div>
          <el-tag v-if="profile?.user.email_verified" type="success">Verified</el-tag>
          <el-button v-else type="primary" plain @click="resendVerification">
            Resend verification
          </el-button>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="flex items-center justify-between gap-3">
            <span class="font-medium">Two-factor authentication</span>
            <el-tag :type="mfaEnabled ? 'success' : 'info'">
              {{ mfaEnabled ? 'Enabled' : 'Disabled' }}
            </el-tag>
          </div>
        </template>
        <div v-if="mfaEnabled" class="space-y-4">
          <p class="text-sm text-muted-foreground">
            Authenticator verification protects password logins. Trusted devices may skip the second step temporarily.
          </p>
          <div class="text-sm">
            Unused recovery codes:
            <strong>{{ profile?.user.recovery_codes_remaining ?? 0 }}</strong>
          </div>
          <div class="flex flex-wrap gap-2">
            <el-button @click="regenerateRecoveryCodes">Regenerate recovery codes</el-button>
            <el-button type="danger" plain @click="disableDialog = true">Disable MFA</el-button>
          </div>
        </div>
        <div v-else class="space-y-4">
          <p class="text-sm text-muted-foreground">
            Use any standard TOTP authenticator. Email verification is required before enrollment.
          </p>
          <el-button type="primary" @click="beginMfa">Enable MFA</el-button>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span class="font-medium">Change password</span>
        </template>
        <div class="max-w-lg">
          <el-form label-position="top">
            <el-form-item label="Current password">
              <el-input v-model="currentPassword" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-form-item label="New password">
              <el-input
                v-model="newPassword"
                type="password"
                show-password
                autocomplete="new-password"
                placeholder="At least 10 characters"
              />
            </el-form-item>
            <el-button type="primary" :loading="changing" @click="changePassword">
              Change password
            </el-button>
          </el-form>
          <div class="text-xs text-muted-foreground mt-3">
            Changing your password revokes other sessions and trusted-device bypasses.
          </div>
        </div>
      </el-card>

      <el-card v-loading="loading" shadow="never">
        <template #header>
          <span class="font-medium">Recent security events</span>
        </template>
        <el-table :data="securityEvents" empty-text="No security events">
          <el-table-column label="Time" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.created_at).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column prop="event_type" label="Event" min-width="180" />
          <el-table-column label="Result" width="100">
            <template #default="{ row }">
              <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                {{ row.success ? 'Success' : 'Failed' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="IP" min-width="140">
            <template #default="{ row }">
              <span class="font-mono text-xs">{{ row.client_ip || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="user_agent" label="Client" min-width="260" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card v-loading="loading" shadow="never">
        <template #header>
          <div class="flex items-center justify-between gap-3">
            <span class="font-medium">Active sessions</span>
            <el-button type="danger" plain @click="logoutAll">Sign out everywhere</el-button>
          </div>
        </template>
        <el-table :data="sessions" empty-text="No active sessions">
          <el-table-column label="Device" min-width="250">
            <template #default="{ row }">
              <div class="flex items-center gap-2">
                <el-tag v-if="row.current" type="success" size="small">Current</el-tag>
                <el-tag v-if="row.mfa_authenticated_at" type="info" size="small">MFA</el-tag>
                <span class="text-sm">{{ row.user_agent || 'Unknown client' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="Last IP" min-width="145">
            <template #default="{ row }">
              <span class="font-mono text-xs">{{ row.last_seen_ip || row.created_ip || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Last seen" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.last_seen_at).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column label="Expires" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.expires_at).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column label="Action" width="110" fixed="right">
            <template #default="{ row }">
              <el-button
                text
                type="danger"
                :disabled="row.current"
                @click="revoke(row as UserSession)"
              >
                Revoke
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-dialog v-model="enrollmentDialog" title="Set up authenticator" width="min(620px, 94vw)">
        <div class="space-y-4">
          <el-alert
            type="info"
            :closable="false"
            title="Add this account to your authenticator"
            description="Use the manual secret below, or copy the provisioning URI into an authenticator that supports it."
          />
          <div>
            <div class="text-xs text-muted-foreground mb-1">Manual secret</div>
            <div class="flex gap-2">
              <el-input :model-value="enrollment?.secret" readonly class="font-mono" />
              <el-button @click="copyText(enrollment?.secret || '', 'Secret copied')">Copy</el-button>
            </div>
          </div>
          <div>
            <div class="text-xs text-muted-foreground mb-1">Provisioning URI</div>
            <div class="flex gap-2">
              <el-input :model-value="enrollment?.provisioning_uri" readonly />
              <el-button @click="copyText(enrollment?.provisioning_uri || '', 'URI copied')">Copy</el-button>
            </div>
          </div>
          <el-form label-position="top">
            <el-form-item label="6-digit code">
              <el-input v-model="enrollmentCode" autocomplete="one-time-code" placeholder="123456" />
            </el-form-item>
          </el-form>
        </div>
        <template #footer>
          <el-button @click="enrollmentDialog = false">Cancel</el-button>
          <el-button type="primary" :loading="confirmingMfa" @click="confirmMfa">
            Verify & enable
          </el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="recoveryDialog" title="Save recovery codes" width="min(560px, 94vw)">
        <el-alert
          type="warning"
          :closable="false"
          title="These codes are shown only now"
          description="Store them in a password manager. Each code can be used once instead of an authenticator code."
          class="mb-4"
        />
        <div class="grid grid-cols-2 gap-2 font-mono text-sm">
          <div v-for="code in recoveryCodes" :key="code" class="border rounded px-3 py-2">
            {{ code }}
          </div>
        </div>
        <template #footer>
          <el-button @click="copyRecoveryCodes">Copy all</el-button>
          <el-button type="primary" @click="recoveryDialog = false">I saved them</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="disableDialog" title="Disable two-factor authentication" width="min(480px, 94vw)">
        <el-alert
          type="warning"
          :closable="false"
          title="This reduces account protection"
          description="MFA cannot be disabled while any workspace membership requires it."
          class="mb-4"
        />
        <el-form label-position="top">
          <el-form-item label="Current password">
            <el-input v-model="disablePassword" type="password" show-password />
          </el-form-item>
          <el-form-item label="Authenticator or recovery code">
            <el-input v-model="disableCode" placeholder="123456 or XXXX-XXXX-XXXX" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="disableDialog = false">Cancel</el-button>
          <el-button type="danger" :loading="disablingMfa" @click="disableMfa">Disable MFA</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>
