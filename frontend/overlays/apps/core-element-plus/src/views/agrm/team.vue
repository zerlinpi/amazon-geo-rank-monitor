<script setup lang="ts">
import type {
  AccountProfile,
  TeamMember,
  WorkspaceInvitation,
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
        <div class="flex items-center justify-between">
          <span class="font-medium">Members</span>
          <el-tag v-if="profile" type="info">{{ profile.workspace.name }} · {{ profile.workspace.role }}</el-tag>
        </div>
      </template>
      <el-table :data="members" empty-text="No members">
        <el-table-column prop="display_name" label="Name" min-width="170" />
        <el-table-column prop="email" label="Email" min-width="220" />
        <el-table-column label="Role" width="150">
          <template #default="{ row }">
            <el-select
              v-if="canManage && (currentRole === 'owner' || !['owner', 'admin'].includes(row.role))"
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
