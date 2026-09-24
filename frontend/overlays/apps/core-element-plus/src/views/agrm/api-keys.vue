<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'ApiKeys' })

const rows = ref<any[]>([])
const loading = ref(false)
const dialog = ref(false)
const name = ref('')
const creating = ref(false)
const createdKey = ref('')
const scopes = ref<string[]>(['*'])
const scopeOptions = [
  { label: 'Full access', value: '*' },
  { label: 'Geo · read', value: 'geo:read' },
  { label: 'Geo · write', value: 'geo:write' },
  { label: 'Monitors · read', value: 'monitors:read' },
  { label: 'Monitors · write', value: 'monitors:write' },
  { label: 'Rank · read', value: 'rank:read' },
  { label: 'Rank · write', value: 'rank:write' },
  { label: 'Billing · read', value: 'billing:read' },
  { label: 'Billing · write', value: 'billing:write' },
  { label: 'API keys · manage', value: 'keys:manage' },
  { label: 'System · read', value: 'system:read' },
]

async function load() {
  loading.value = true
  try {
    rows.value = await agrmApi.getApiKeys()
  }
  finally {
    loading.value = false
  }
}

async function create() {
  if (!name.value.trim()) {
    ElMessage.warning('Key name is required')
    return
  }
  creating.value = true
  try {
    const result: any = await agrmApi.createApiKey(name.value.trim(), scopes.value)
    createdKey.value = result.plaintext
    name.value = ''
    scopes.value = ['*']
    dialog.value = false
    await load()
  }
  finally {
    creating.value = false
  }
}

async function revoke(row: any) {
  await ElMessageBox.confirm(
    'Revoke API key ' + row.prefix + '? Existing integrations using it will stop working.',
    'Revoke key',
    { type: 'warning' },
  )
  await agrmApi.revokeApiKey(row.id)
  ElMessage.success('API Key revoked')
  await load()
}

async function copyKey() {
  await navigator.clipboard.writeText(createdKey.value)
  ElMessage.success('Copied')
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Developer access</div>
        <h1 class="text-2xl font-semibold mt-1">API Keys</h1>
        <p class="text-sm text-muted-foreground mt-1">Keys are tenant-scoped. Plaintext is shown only once at creation.</p>
      </div>
      <el-button type="primary" @click="dialog = true">Create API Key</el-button>
    </div>

    <el-alert
      v-if="createdKey"
      type="success"
      :closable="false"
      title="New key — copy it now"
      class="mb-4"
    >
      <div class="mt-3 flex gap-2">
        <el-input :model-value="createdKey" readonly />
        <el-button @click="copyKey">Copy</el-button>
        <el-button @click="createdKey = ''">Dismiss</el-button>
      </div>
    </el-alert>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="rows">
        <el-table-column prop="name" label="Name" min-width="180" />
        <el-table-column prop="prefix" label="Prefix" min-width="160">
          <template #default="{ row }"><span class="font-mono">{{ row.prefix }}</span></template>
        </el-table-column>
        <el-table-column label="Scopes" min-width="240">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag v-for="scope in row.scopes || ['*']" :key="scope" size="small" type="info">{{ scope }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Created" min-width="170">
          <template #default="{ row }">{{ row.created_at ? new Date(row.created_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="Last used" min-width="170">
          <template #default="{ row }">{{ row.last_used_at ? new Date(row.last_used_at).toLocaleString() : 'Never' }}</template>
        </el-table-column>
        <el-table-column label="Status" width="110">
          <template #default="{ row }">
            <el-tag :type="row.revoked_at ? 'info' : 'success'">{{ row.revoked_at ? 'Revoked' : 'Active' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Action" width="100">
          <template #default="{ row }">
            <el-button v-if="!row.revoked_at" text type="danger" @click="revoke(row)">Revoke</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" title="Create API Key" width="min(480px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="Name">
          <el-input v-model="name" placeholder="ChatGPT MCP, CI, analyst laptop..." />
        </el-form-item>
        <el-form-item label="Permissions">
          <el-select v-model="scopes" multiple class="w-full" placeholder="Select scopes">
            <el-option
              v-for="option in scopeOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <div class="mt-2 text-xs text-muted-foreground">
            Use Full access for admin/UI keys. Use only the scopes an automation actually needs.
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">Cancel</el-button>
        <el-button type="primary" :loading="creating" @click="create">Create</el-button>
      </template>
    </el-dialog>
  </div>
</template>
