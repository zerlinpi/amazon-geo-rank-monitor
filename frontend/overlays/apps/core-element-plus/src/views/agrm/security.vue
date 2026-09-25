<script setup lang="ts">
import type { AccountProfile, AuthSecurityEvent, UserSession } from '@/api/agrm'
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

const isHuman = computed(() => appAccountStore.authMode === 'session')

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
    ElMessage.error(error.response?.data?.detail || 'Failed to load sessions')
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
      'Sign out every active device, including this browser?',
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
        Manage your password and active browser sessions.
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
            Changing your password revokes every other active session.
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
          <el-table-column label="Created" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.created_at).toLocaleString() }}
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
    </template>
  </div>
</template>
