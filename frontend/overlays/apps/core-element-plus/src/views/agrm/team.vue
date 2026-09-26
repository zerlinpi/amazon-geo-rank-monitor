<script setup lang="ts">
import type {
  AccountProfile,
  ScimAdminGroup,
  TeamMember,
  WorkspaceInvitation,
  WorkspaceScimConfig,
  WorkspaceSsoConfig,
  WorkspaceVerificationPolicy,
} from '@/api/agrm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'Team' })

const appAccountStore = useAppAccountStore()
const loading = ref(false)
const members = ref<TeamMember[]>([])
const invitations = ref<WorkspaceInvitation[]>([])
const profile = ref<AccountProfile>()
const inviteDialog = ref(false)
const inviteEmail = ref('')
const inviteRole = ref('viewer')
const inviting = ref(false)
const createdInviteLink = ref('')
const requireMfa = ref(false)
const updatingPolicy = ref(false)
const verificationPolicy = ref<WorkspaceVerificationPolicy>()
const savingVerificationPolicy = ref(false)
const verificationForm = reactive({
  mode: 'inherit' as 'inherit' | 'on' | 'off',
  minConfidence: 75,
  maxProbes: 3,
})
const ssoConfig = ref<WorkspaceSsoConfig | null>(null)
const savingSso = ref(false)
const updatingSsoEnforcement = ref(false)
const testingSso = ref(false)
const scimConfig = ref<WorkspaceScimConfig>()
const scimGroups = ref<ScimAdminGroup[]>([])
const scimEnabled = ref(false)
const scimDefaultRole = ref('viewer')
const savingScim = ref(false)
const rotatingScimToken = ref(false)
const scimTokenDialog = ref(false)
const scimToken = ref('')
const ssoForm = reactive({
  provider_type: 'oidc',
  display_name: 'Enterprise SSO',
  issuer_url: '',
  client_id: '',
  client_secret: '',
  email_domains: '',
  auto_join: false,
  enabled: true,
})

const currentRole = computed(() => profile.value?.workspace.role)
const canManage = computed(() => ['owner', 'admin'].includes(currentRole.value || ''))
const roleOptions = computed(() => (
  currentRole.value === 'owner'
    ? ['owner', 'admin', 'analyst', 'viewer']
    : ['analyst', 'viewer']
))

function invitationLink(token: string) {
  return `${location.origin}${location.pathname}#/login?invite=${encodeURIComponent(token)}`
}

async function load() {
  loading.value = true
  try {
    profile.value = await agrmApi.getMe()
    members.value = await agrmApi.getTeamMembers()
    const [policy, loadedVerificationPolicy] = await Promise.all([
      agrmApi.getWorkspaceSecurityPolicy(),
      agrmApi.getWorkspaceVerificationPolicy(),
    ])
    requireMfa.value = policy.require_mfa
    verificationPolicy.value = loadedVerificationPolicy
    verificationForm.mode = loadedVerificationPolicy.enabled == null
      ? 'inherit'
      : loadedVerificationPolicy.enabled ? 'on' : 'off'
    verificationForm.minConfidence = Math.round(
      Number(
        loadedVerificationPolicy.min_confidence
        ?? loadedVerificationPolicy.runtime.min_confidence,
      ) * 100,
    )
    verificationForm.maxProbes = (
      loadedVerificationPolicy.max_upstream_probes_per_run
      ?? loadedVerificationPolicy.runtime.max_upstream_probes_per_run
    )
    if (currentRole.value === 'owner') {
      const [loadedSso, loadedScim, loadedScimGroups] = await Promise.all([
        agrmApi.getWorkspaceSsoConfig(),
        agrmApi.getWorkspaceScimConfig(),
        agrmApi.getScimGroups(),
      ])
      ssoConfig.value = loadedSso
      scimConfig.value = loadedScim
      scimGroups.value = loadedScimGroups
      scimEnabled.value = loadedScim.enabled
      scimDefaultRole.value = loadedScim.default_role
      if (ssoConfig.value) {
        ssoForm.provider_type = ssoConfig.value.provider_type
        ssoForm.display_name = ssoConfig.value.display_name
        ssoForm.issuer_url = ssoConfig.value.issuer_url
        ssoForm.client_id = ssoConfig.value.client_id
        ssoForm.client_secret = ''
        ssoForm.email_domains = ssoConfig.value.email_domains.join(', ')
        ssoForm.auto_join = ssoConfig.value.auto_join
        ssoForm.enabled = ssoConfig.value.enabled
      }
    }
    else {
      ssoConfig.value = null
      scimConfig.value = undefined
      scimGroups.value = []
    }
    if (canManage.value) {
      invitations.value = await agrmApi.getTeamInvitations()
    }
    else {
      invitations.value = []
    }
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load team')
  }
  finally {
    loading.value = false
  }
}

async function updateMfaPolicy(value: string | number | boolean) {
  if (currentRole.value !== 'owner') {
    return
  }
  const enabled = value === true
  updatingPolicy.value = true
  try {
    const result = await agrmApi.updateWorkspaceSecurityPolicy(enabled)
    requireMfa.value = result.require_mfa
    ElMessage.success(result.require_mfa ? 'Workspace now requires MFA' : 'Workspace MFA requirement disabled')
    await load()
  }
  catch (error: any) {
    requireMfa.value = !enabled
    ElMessage.error(error.response?.data?.detail || 'Failed to update MFA policy')
  }
  finally {
    updatingPolicy.value = false
  }
}

async function saveVerificationPolicy() {
  if (!canManage.value) {
    return
  }
  savingVerificationPolicy.value = true
  try {
    verificationPolicy.value = await agrmApi.updateWorkspaceVerificationPolicy({
      enabled: verificationForm.mode === 'inherit'
        ? null
        : verificationForm.mode === 'on',
      min_confidence: verificationForm.mode === 'inherit'
        ? null
        : verificationForm.minConfidence / 100,
      max_upstream_probes_per_run: verificationForm.mode === 'inherit'
        ? null
        : verificationForm.maxProbes,
    })
    ElMessage.success('Workspace Auto Strict defaults updated')
    await load()
  }
  catch (error: any) {
    ElMessage.error(
      error.response?.data?.detail
      || 'Failed to update workspace Auto Strict defaults',
    )
  }
  finally {
    savingVerificationPolicy.value = false
  }
}

function applySsoProviderTemplate(provider: string | number | boolean) {
  const value = String(provider)
  ssoForm.provider_type = value
  if (value === 'google') {
    ssoForm.display_name = 'Google Workspace'
    ssoForm.issuer_url = 'https://accounts.google.com'
  }
  else if (value === 'entra') {
    ssoForm.display_name = 'Microsoft Entra ID'
    if (ssoForm.issuer_url === 'https://accounts.google.com') {
      ssoForm.issuer_url = ''
    }
  }
  else if (!ssoForm.display_name.trim()) {
    ssoForm.display_name = 'Enterprise SSO'
  }
}

async function saveSso() {
  if (currentRole.value !== 'owner') {
    return
  }
  const domains = ssoForm.email_domains
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
  if (!ssoForm.issuer_url.trim() || !ssoForm.client_id.trim() || !domains.length) {
    ElMessage.warning('Issuer URL, Client ID and at least one email domain are required')
    return
  }
  savingSso.value = true
  try {
    ssoConfig.value = await agrmApi.updateWorkspaceSsoConfig({
      provider_type: ssoForm.provider_type,
      display_name: ssoForm.display_name.trim(),
      issuer_url: ssoForm.issuer_url.trim(),
      client_id: ssoForm.client_id.trim(),
      ...(ssoForm.client_secret.trim()
        ? { client_secret: ssoForm.client_secret.trim() }
        : {}),
      email_domains: domains,
      auto_join: ssoForm.auto_join,
      enabled: ssoForm.enabled,
    })
    ssoForm.client_secret = ''
    ElMessage.success(
      ssoConfig.value.verified_at
        ? 'SSO configuration saved'
        : 'SSO configuration saved. Test sign-in before enforcement.',
    )
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to save SSO configuration')
  }
  finally {
    savingSso.value = false
  }
}

async function testSso() {
  if (!ssoConfig.value?.enabled || !profile.value) {
    ElMessage.warning('Save and enable the SSO configuration first')
    return
  }
  testingSso.value = true
  try {
    const started = await agrmApi.startSso(
      profile.value.workspace.id,
      profile.value.user.email,
    )
    window.location.assign(started.authorization_url)
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Unable to start SSO test')
    testingSso.value = false
  }
}

async function updateSsoEnforcement(value: string | number | boolean) {
  if (currentRole.value !== 'owner') {
    return
  }
  const enabled = value === true
  updatingSsoEnforcement.value = true
  try {
    ssoConfig.value = await agrmApi.updateWorkspaceSsoEnforcement(enabled)
    ElMessage.success(
      enabled
        ? 'Enterprise SSO is now required for human access'
        : 'Enterprise SSO enforcement disabled',
    )
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update SSO enforcement')
  }
  finally {
    updatingSsoEnforcement.value = false
  }
}

async function saveScim() {
  if (currentRole.value !== 'owner') {
    return
  }
  savingScim.value = true
  try {
    scimConfig.value = await agrmApi.updateWorkspaceScimConfig(
      scimEnabled.value,
      scimDefaultRole.value,
    )
    ElMessage.success(
      scimConfig.value.enabled
        ? 'SCIM provisioning enabled'
        : 'SCIM provisioning disabled',
    )
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update SCIM provisioning')
  }
  finally {
    savingScim.value = false
  }
}

async function rotateScimToken() {
  if (currentRole.value !== 'owner') {
    return
  }
  try {
    if (scimConfig.value?.has_token) {
      await ElMessageBox.confirm(
        'Rotating the SCIM token immediately invalidates the previous provisioning token. Update your identity provider after rotation.',
        'Rotate SCIM token',
        { type: 'warning', confirmButtonText: 'Rotate token' },
      )
    }
    rotatingScimToken.value = true
    const result = await agrmApi.rotateScimToken()
    scimToken.value = result.token
    scimTokenDialog.value = true
    scimEnabled.value = true
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to rotate SCIM token')
  }
  finally {
    rotatingScimToken.value = false
  }
}

async function copyScimToken() {
  if (!scimToken.value) {
    return
  }
  await navigator.clipboard.writeText(scimToken.value)
  ElMessage.success('SCIM token copied')
}

async function mapScimGroupRole(group: ScimAdminGroup, role: string) {
  try {
    await agrmApi.mapScimGroupRole(group.id, role || null)
    ElMessage.success(role ? `Group mapped to ${role}` : 'Group role mapping cleared')
    scimGroups.value = await agrmApi.getScimGroups()
    members.value = await agrmApi.getTeamMembers()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to map SCIM group role')
    scimGroups.value = await agrmApi.getScimGroups().catch(() => scimGroups.value)
  }
}

async function invite() {
  if (!inviteEmail.value.trim()) {
    ElMessage.warning('Email is required')
    return
  }
  inviting.value = true
  try {
    const created = await agrmApi.createTeamInvitation(
      inviteEmail.value.trim(),
      inviteRole.value,
    )
    if (created.invitation_token) {
      createdInviteLink.value = invitationLink(created.invitation_token)
    }
    inviteEmail.value = ''
    inviteRole.value = 'viewer'
    inviteDialog.value = false
    ElMessage.success('Invitation created')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to create invitation')
  }
  finally {
    inviting.value = false
  }
}

async function copyInvite() {
  await navigator.clipboard.writeText(createdInviteLink.value)
  ElMessage.success('Invitation link copied')
}

async function changeRole(row: TeamMember, role: string) {
  if (role === row.role) {
    return
  }
  try {
    await agrmApi.updateTeamMemberRole(row.user_id, role)
    ElMessage.success('Role updated')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update role')
    await load()
  }
}

async function removeMember(row: TeamMember) {
  try {
    await ElMessageBox.confirm(
      `Remove ${row.display_name || row.email} from this workspace?`,
      'Remove member',
      { type: 'warning', confirmButtonText: 'Remove' },
    )
    await agrmApi.removeTeamMember(row.user_id)
    ElMessage.success('Member removed')
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to remove member')
  }
}

async function switchWorkspace(ownerId: string) {
  if (!profile.value || ownerId === profile.value.workspace.id) {
    return
  }
  try {
    const session = await agrmApi.switchWorkspace(ownerId)
    appAccountStore.applySession(session)
    ElMessage.success(`Switched to ${session.workspace.name}`)
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to switch workspace')
  }
}

function invitationStatus(row: WorkspaceInvitation) {
  if (row.accepted_at) {
    return 'Accepted'
  }
  if (new Date(row.expires_at).getTime() < Date.now()) {
    return 'Expired'
  }
  return 'Pending'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Workspace</div>
        <h1 class="text-2xl font-semibold mt-1">Team</h1>
        <p class="text-sm text-muted-foreground mt-1">
          Manage human access separately from API keys used by automation.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <el-select
          v-if="profile && profile.memberships.length > 1"
          :model-value="profile.workspace.id"
          style="width: 220px"
          @change="switchWorkspace"
        >
          <el-option
            v-for="membership in profile.memberships"
            :key="membership.owner_id"
            :label="membership.workspace_name || membership.owner_id"
            :value="membership.owner_id"
          />
        </el-select>
        <el-button v-if="canManage" type="primary" @click="inviteDialog = true">
          Invite member
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="createdInviteLink"
      type="success"
      :closable="false"
      title="Invitation created — share this link securely"
    >
      <div class="mt-3 flex gap-2">
        <el-input :model-value="createdInviteLink" readonly />
        <el-button @click="copyInvite">Copy</el-button>
        <el-button @click="createdInviteLink = ''">Dismiss</el-button>
      </div>
    </el-alert>

    <el-card shadow="never">
      <template #header>
        <span class="font-medium">Workspace security</span>
      </template>
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div class="font-medium">Require two-factor authentication</div>
          <div class="text-sm text-muted-foreground mt-1">
            When enabled, human members must complete MFA before workspace resources are accessible.
          </div>
        </div>
        <div class="flex items-center gap-3">
          <el-tag :type="requireMfa ? 'warning' : 'info'">
            {{ requireMfa ? 'Required' : 'Optional' }}
          </el-tag>
          <el-switch
            v-if="currentRole === 'owner'"
            :model-value="requireMfa"
            :loading="updatingPolicy"
            @change="updateMfaPolicy"
          />
        </div>
      </div>
      <el-alert
        v-if="currentRole === 'owner' && !requireMfa"
        class="mt-4"
        type="info"
        :closable="false"
        title="All current members must enable MFA before this policy can be turned on."
      />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-medium">Automatic strict verification</span>
            <div class="text-xs text-muted-foreground mt-1">
              Workspace defaults used by managed Monitors set to Inherit.
            </div>
          </div>
          <div v-if="verificationPolicy" class="flex items-center gap-2">
            <el-tag
              :type="verificationPolicy.effective.enabled ? 'success' : 'info'"
            >
              {{ verificationPolicy.effective.enabled ? 'Effective On' : 'Effective Off' }}
            </el-tag>
            <el-tag
              v-if="!verificationPolicy.runtime.enabled"
              type="warning"
            >
              Runtime kill switch Off
            </el-tag>
          </div>
        </div>
      </template>

      <el-form label-position="top" class="max-w-3xl">
        <div class="grid gap-x-4 md:grid-cols-3">
          <el-form-item label="Workspace default">
            <el-select
              v-model="verificationForm.mode"
              class="w-full"
              :disabled="!canManage"
            >
              <el-option label="Inherit runtime default" value="inherit" />
              <el-option label="On" value="on" />
              <el-option label="Off" value="off" />
            </el-select>
          </el-form-item>
          <el-form-item
            v-if="verificationForm.mode !== 'inherit'"
            label="Minimum confidence"
          >
            <div class="flex items-center gap-2">
              <el-input-number
                v-model="verificationForm.minConfidence"
                :min="1"
                :max="100"
                :step="5"
                :disabled="!canManage"
              />
              <span class="text-sm text-muted-foreground">%</span>
            </div>
          </el-form-item>
          <el-form-item
            v-if="verificationForm.mode !== 'inherit'"
            label="Max paid strict probes / run"
          >
            <el-input-number
              v-model="verificationForm.maxProbes"
              :min="0"
              :max="100"
              :disabled="!canManage"
            />
          </el-form-item>
        </div>

        <el-alert
          v-if="verificationPolicy"
          :type="verificationPolicy.runtime.enabled ? 'info' : 'warning'"
          :closable="false"
        >
          <template #title>
            Effective policy:
            {{ verificationPolicy.effective.enabled ? 'On' : 'Off' }}
            · confidence
            {{ Math.round(Number(verificationPolicy.effective.min_confidence) * 100) }}%
            · max
            {{ verificationPolicy.effective.max_upstream_probes_per_run }}
            strict upstream probes/run
          </template>
          <div class="mt-1 text-xs">
            The runtime switch is the global safety kill switch. Monitor-level overrides
            are resolved after this workspace default when a job is queued.
          </div>
        </el-alert>

        <div v-if="canManage" class="mt-4">
          <el-button
            type="primary"
            :loading="savingVerificationPolicy"
            @click="saveVerificationPolicy"
          >
            Save verification defaults
          </el-button>
        </div>
      </el-form>
    </el-card>

    <el-card v-if="currentRole === 'owner'" shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-medium">Enterprise SSO</span>
            <div class="text-xs text-muted-foreground mt-1">
              Google Workspace, Microsoft Entra ID, or any RS256 OpenID Connect provider.
            </div>
          </div>
          <div class="flex items-center gap-2">
            <el-tag v-if="ssoConfig?.verified_at" type="success">Verified</el-tag>
            <el-tag v-else type="info">Not verified</el-tag>
            <el-tag v-if="ssoConfig?.enforce_sso" type="warning">Required</el-tag>
          </div>
        </div>
      </template>

      <el-form label-position="top" class="max-w-3xl">
        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item label="Provider">
            <el-select
              :model-value="ssoForm.provider_type"
              class="w-full"
              @change="applySsoProviderTemplate"
            >
              <el-option label="Google Workspace" value="google" />
              <el-option label="Microsoft Entra ID" value="entra" />
              <el-option label="Generic OIDC" value="oidc" />
            </el-select>
          </el-form-item>
          <el-form-item label="Display name">
            <el-input v-model="ssoForm.display_name" />
          </el-form-item>
        </div>

        <el-form-item label="Issuer URL">
          <el-input
            v-model="ssoForm.issuer_url"
            placeholder="https://login.microsoftonline.com/<tenant-id>/v2.0"
          />
          <div class="text-xs text-muted-foreground mt-1">
            Entra must use a tenant-specific v2.0 issuer. Google uses https://accounts.google.com.
          </div>
        </el-form-item>

        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item label="Client ID">
            <el-input v-model="ssoForm.client_id" />
          </el-form-item>
          <el-form-item label="Client secret">
            <el-input
              v-model="ssoForm.client_secret"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="ssoConfig ? 'Leave blank to keep current secret' : 'Required on first save'"
            />
          </el-form-item>
        </div>

        <el-form-item label="Allowed email domains">
          <el-input
            v-model="ssoForm.email_domains"
            placeholder="example.com, subsidiary.example.com"
          />
        </el-form-item>

        <div class="flex flex-wrap gap-5 mb-5">
          <el-checkbox v-model="ssoForm.auto_join">
            JIT-create unknown users as Viewer
          </el-checkbox>
          <el-checkbox v-model="ssoForm.enabled">
            Enable this SSO connection
          </el-checkbox>
        </div>

        <div class="flex flex-wrap gap-2">
          <el-button type="primary" :loading="savingSso" @click="saveSso">
            Save SSO
          </el-button>
          <el-button
            :disabled="!ssoConfig?.enabled"
            :loading="testingSso"
            @click="testSso"
          >
            Test SSO
          </el-button>
        </div>
      </el-form>

      <el-divider />

      <div class="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div class="font-medium">Require Enterprise SSO</div>
          <div class="text-sm text-muted-foreground mt-1">
            Enforcement can only be enabled after a successful Owner SSO test.
            A team-manage API key may disable enforcement as a break-glass recovery path.
          </div>
        </div>
        <el-switch
          :model-value="ssoConfig?.enforce_sso || false"
          :disabled="!ssoConfig?.enabled || !ssoConfig?.verified_at"
          :loading="updatingSsoEnforcement"
          @change="updateSsoEnforcement"
        />
      </div>
    </el-card>

    <el-card v-if="currentRole === 'owner'" shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-medium">SCIM provisioning</span>
            <div class="text-xs text-muted-foreground mt-1">
              Automate employee onboarding, offboarding and group-driven workspace roles.
            </div>
          </div>
          <div class="flex items-center gap-2">
            <el-tag :type="scimConfig?.enabled ? 'success' : 'info'">
              {{ scimConfig?.enabled ? 'Enabled' : 'Disabled' }}
            </el-tag>
            <el-tag v-if="scimConfig?.has_token" type="info">
              Token {{ scimConfig.token_prefix }}
            </el-tag>
          </div>
        </div>
      </template>

      <div class="grid lg:grid-cols-2 gap-5">
        <div class="space-y-4">
          <el-alert
            type="info"
            :closable="false"
            title="Provisioning endpoint"
          >
            <div class="mt-2 font-mono text-xs break-all">/scim/v2</div>
            <div class="text-xs mt-2">
              Configure your identity provider with the API origin plus this path and the Bearer token generated below.
            </div>
          </el-alert>

          <el-form label-position="top">
            <el-form-item label="Default workspace role">
              <el-select v-model="scimDefaultRole" class="w-full">
                <el-option label="Viewer" value="viewer" />
                <el-option label="Analyst" value="analyst" />
                <el-option label="Admin" value="admin" />
              </el-select>
              <div class="text-xs text-muted-foreground mt-1">
                Used when no SCIM group with a mapped role applies. SCIM can never grant Owner.
              </div>
            </el-form-item>
            <el-form-item>
              <el-checkbox v-model="scimEnabled">
                Enable SCIM provisioning
              </el-checkbox>
            </el-form-item>
          </el-form>

          <div class="flex flex-wrap gap-2">
            <el-button type="primary" :loading="savingScim" @click="saveScim">
              Save SCIM settings
            </el-button>
            <el-button :loading="rotatingScimToken" @click="rotateScimToken">
              {{ scimConfig?.has_token ? 'Rotate token' : 'Generate token' }}
            </el-button>
          </div>

          <el-alert
            v-if="scimConfig?.has_token"
            type="warning"
            :closable="false"
            title="Provisioning tokens are shown only once."
            description="Rotating the token immediately invalidates the previous Bearer token."
          />
        </div>

        <div>
          <div class="font-medium mb-1">IdP groups → workspace roles</div>
          <div class="text-sm text-muted-foreground mb-3">
            Groups appear here after your identity provider syncs them through SCIM.
            If a user belongs to multiple mapped groups, Admin wins over Analyst, then Viewer.
          </div>
          <el-table :data="scimGroups" empty-text="No SCIM groups synced yet" max-height="360">
            <el-table-column prop="display_name" label="Group" min-width="160">
              <template #default="{ row }">
                <div>{{ row.display_name }}</div>
                <div v-if="row.external_id" class="text-xs text-muted-foreground">
                  {{ row.external_id }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="Members" width="90">
              <template #default="{ row }">
                {{ row.members?.length || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="Role mapping" min-width="150">
              <template #default="{ row }">
                <el-select
                  :model-value="row.mapped_role || ''"
                  size="small"
                  class="w-full"
                  @change="(value: string) => mapScimGroupRole(row as ScimAdminGroup, value)"
                >
                  <el-option label="No mapping" value="" />
                  <el-option label="Viewer" value="viewer" />
                  <el-option label="Analyst" value="analyst" />
                  <el-option label="Admin" value="admin" />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span class="font-medium">Members</span>
          <el-tag v-if="profile" type="info">{{ profile.workspace.name }} · {{ profile.workspace.role }}</el-tag>
        </div>
      </template>
      <el-table :data="members" empty-text="No members">
        <el-table-column prop="display_name" label="Name" min-width="170" />
        <el-table-column prop="email" label="Email" min-width="220" />
        <el-table-column label="Access" width="130">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag v-if="row.scim_managed" type="primary" size="small">SCIM</el-tag>
              <el-tag v-if="row.suspended_at" type="danger" size="small">Suspended</el-tag>
              <el-tag v-if="!row.scim_managed && !row.suspended_at" type="info" size="small">Manual</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="MFA" width="100">
          <template #default="{ row }">
            <el-tag :type="row.mfa_enabled ? 'success' : 'info'" size="small">
              {{ row.mfa_enabled ? 'On' : 'Off' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Role" width="150">
          <template #default="{ row }">
            <el-select
              v-if="canManage && !row.scim_managed && !row.suspended_at && (currentRole === 'owner' || !['owner', 'admin'].includes(row.role))"
              :model-value="row.role"
              size="small"
              @change="(value: string) => changeRole(row as TeamMember, value)"
            >
              <el-option
                v-for="role in roleOptions"
                :key="role"
                :label="role"
                :value="role"
              />
            </el-select>
            <el-tag v-else type="info">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Joined" min-width="170">
          <template #default="{ row }">
            {{ row.created_at ? new Date(row.created_at).toLocaleString() : '—' }}
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="Action" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              text
              type="danger"
              :disabled="row.user_id === profile?.user.id"
              @click="removeMember(row as TeamMember)"
            >
              Remove
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="canManage" shadow="never">
      <template #header>
        <span class="font-medium">Invitations</span>
      </template>
      <el-table :data="invitations" empty-text="No invitations">
        <el-table-column prop="email" label="Email" min-width="220" />
        <el-table-column prop="role" label="Role" width="120" />
        <el-table-column label="Status" width="120">
          <template #default="{ row }">
            <el-tag :type="invitationStatus(row as WorkspaceInvitation) === 'Pending' ? 'warning' : 'info'">
              {{ invitationStatus(row as WorkspaceInvitation) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Expires" min-width="170">
          <template #default="{ row }">
            {{ new Date(row.expires_at).toLocaleString() }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="scimTokenDialog"
      title="SCIM provisioning token"
      width="min(620px, 94vw)"
      :close-on-click-modal="false"
      @closed="scimToken = ''"
    >
      <el-alert
        type="warning"
        :closable="false"
        title="Copy this token now"
        description="The plaintext token is not stored in the browser and cannot be shown again after this dialog is closed."
      />
      <div class="mt-4 flex gap-2">
        <el-input :model-value="scimToken" readonly type="textarea" :rows="3" />
        <el-button @click="copyScimToken">Copy</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="scimTokenDialog = false">
          I saved the token
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="inviteDialog" title="Invite member" width="min(480px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="Email">
          <el-input v-model="inviteEmail" placeholder="teammate@company.com" />
        </el-form-item>
        <el-form-item label="Role">
          <el-select v-model="inviteRole" class="w-full">
            <el-option
              v-for="role in currentRole === 'owner' ? ['admin', 'analyst', 'viewer'] : ['analyst', 'viewer']"
              :key="role"
              :label="role"
              :value="role"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteDialog = false">Cancel</el-button>
        <el-button type="primary" :loading="inviting" @click="invite">Create invitation</el-button>
      </template>
    </el-dialog>
  </div>
</template>
