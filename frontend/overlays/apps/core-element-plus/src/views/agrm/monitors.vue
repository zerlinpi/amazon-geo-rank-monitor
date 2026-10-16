<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi, type GeoProfile, type Monitor, type RankJob } from '@/api/agrm'
import { useAppAccountStore } from '@/store/modules/app/account'
import { apiErrorMessage } from '@/utils/api-error'
import MonitorEditor from './components/MonitorEditor.vue'
import MonitorActivity from './components/MonitorActivity.vue'

defineOptions({ name: 'Monitors' })

const router = useRouter()
const loading = ref(false)
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const dialog = ref(false)
const editing = ref<Monitor | null>(null)
const loadError = ref('')
const query = ref('')
const busy = ref<string[]>([])
const activityOpen = ref(false)
const activityMonitor = ref<Monitor | null>(null)
const queuedJob = ref<RankJob | null>(null)
const account = useAppAccountStore()
const canWrite = computed(() => !account.permissions.includes('viewer'))
const filtered = computed(() => {
  const text = query.value.trim().toLowerCase()
  return monitors.value.filter(row => [row.name, row.keyword, ...row.asins].some(value => value.toLowerCase().includes(text)))
})
const policyDialog = ref(false)
const policySubmitting = ref(false)
const policyMonitor = ref<Monitor | null>(null)
const policyForm = reactive({
  mode: 'inherit' as 'inherit' | 'on' | 'off',
  minConfidence: 75,
  maxProbes: 3,
})

async function load() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const [monitorData, geoData] = await Promise.all([
      agrmApi.getMonitors(),
      agrmApi.getGeoProfiles(),
    ])
    monitors.value = monitorData
    geos.value = geoData
  }
  catch {
    loadError.value = 'Unable to load monitors and regions. Please try again.'
  }
  finally {
    loading.value = false
  }
}

function openEditor(row: Monitor | null = null) {
  editing.value = row
  dialog.value = true
}

function saved(row: Monitor) {
  const index = monitors.value.findIndex(item => item.id === row.id)
  if (index < 0) monitors.value.push(row)
  else monitors.value[index] = row
  ElMessage.success(editing.value ? 'Monitor updated' : 'Monitor created. Choose Run now when ready.')
}

function results(row: Monitor, job: RankJob | null = null) {
  activityMonitor.value = row
  queuedJob.value = job
  activityOpen.value = true
}

function frequency(row: Monitor) {
  const labels: Record<string, string> = {
    '0 * * * *': 'Every hour (UTC)',
    '0 */6 * * *': 'Every 6 hours (UTC)',
    '0 9 * * *': 'Daily at 09:00 UTC',
  }
  return row.schedule ? labels[row.schedule] ?? `${row.schedule} (UTC)` : 'Manual only'
}

function policyMode(row: Monitor): 'inherit' | 'on' | 'off' {
  if (row.auto_strict_enabled == null) {
    return 'inherit'
  }
  return row.auto_strict_enabled ? 'on' : 'off'
}

function policyLabel(row: Monitor) {
  const mode = policyMode(row)
  if (mode === 'inherit') {
    return 'Inherit'
  }
  if (mode === 'off') {
    return 'Off'
  }
  const confidence = row.auto_strict_min_confidence == null
    ? 75
    : Math.round(Number(row.auto_strict_min_confidence) * 100)
  const maxProbes = row.auto_strict_max_probes_per_run ?? 3
  return `On · ${confidence}% · max ${maxProbes}`
}

function openPolicy(row: Monitor) {
  policyMonitor.value = row
  policyForm.mode = policyMode(row)
  policyForm.minConfidence = row.auto_strict_min_confidence == null
    ? 75
    : Math.round(Number(row.auto_strict_min_confidence) * 100)
  policyForm.maxProbes = row.auto_strict_max_probes_per_run ?? 3
  policyDialog.value = true
}

async function savePolicy() {
  if (!policyMonitor.value) {
    return
  }
  policySubmitting.value = true
  try {
    await agrmApi.updateMonitor(policyMonitor.value.id, {
      auto_strict_enabled: (
        policyForm.mode === 'inherit'
          ? null
          : policyForm.mode === 'on'
      ),
      auto_strict_min_confidence: (
        policyForm.mode === 'inherit'
          ? null
          : policyForm.minConfidence / 100
      ),
      auto_strict_max_probes_per_run: (
        policyForm.mode === 'inherit'
          ? null
          : policyForm.maxProbes
      ),
    })
    ElMessage.success('Auto strict policy updated')
    policyDialog.value = false
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update auto strict policy')
  }
  finally {
    policySubmitting.value = false
  }
}

async function toggleEnabled(row: Monitor) {
  try {
    await agrmApi.updateMonitor(row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? 'Monitor disabled' : 'Monitor enabled')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update monitor')
  }
}

async function remove(row: Monitor) {
  try {
    await ElMessageBox.confirm(
      `Delete monitor "${row.name}"? Existing rank history will be retained.`,
      'Delete monitor',
      { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' },
    )
    await agrmApi.deleteMonitor(row.id)
    ElMessage.success('Monitor deleted')
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to delete monitor')
  }
}

function openAlerts(row: Monitor) {
  void router.push({
    path: '/workspace/alerts',
    query: { monitor: row.id },
  })
}

async function run(row: Monitor, forceStrict = false) {
  if (busy.value.includes(row.id)) return
  busy.value.push(row.id)
  try {
    if (forceStrict) {
      await ElMessageBox.confirm(
        'Force strict verification for this run? Additional provider requests can incur upstream charges and remain subject to the configured probe limit.',
        'Force strict verification',
        { type: 'warning', confirmButtonText: 'Queue verified run', cancelButtonText: 'Cancel' },
      )
    }
    const job = await agrmApi.runMonitor(row.id, forceStrict)
    results(row, job)
  }
  catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, 'Unable to queue this monitor. Check Results before trying again.'))
  }
  finally {
    busy.value = busy.value.filter(id => id !== row.id)
  }
}

function more(command: string, row: Monitor) {
  if (command === 'alerts') openAlerts(row)
  if (command === 'policy') openPolicy(row)
  if (command === 'verify') void run(row, true)
  if (command === 'toggle') void toggleEnabled(row)
  if (command === 'delete') void remove(row)
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Scheduled observation</div>
        <h1 class="text-2xl font-semibold mt-1">Monitors</h1>
        <p class="text-sm text-muted-foreground mt-1">Reusable keyword + ASIN + geographic profile definitions.</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <el-button :loading="loading" @click="load">Refresh</el-button>
        <el-button v-if="canWrite" type="primary" :disabled="loading || !!loadError || !geos.some(geo => geo.enabled)" @click="openEditor()">Create monitor</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <el-alert v-if="!loading && !loadError && !geos.some(geo => geo.enabled)" title="Add a region before creating your first monitor" type="info" :closable="false">
      <p>Start with one delivery ZIP. Each selected region adds a probe to a run.</p>
      <el-button v-if="canWrite" class="mt-2" @click="router.push('/ranking/geo-profiles')">Add Geo Profile</el-button>
      <p v-else>Ask a workspace administrator to create a region and monitor.</p>
    </el-alert>
    <el-input v-if="monitors.length" v-model="query" aria-label="Find a monitor" placeholder="Search name, keyword or ASIN" clearable />
    <div v-loading="loading" class="min-h-24">
      <el-empty v-if="!loading && !loadError && !filtered.length" :description="monitors.length ? 'No monitors match your search.' : 'No monitors yet. Create one, then choose Run now to collect your first result.'" />
      <div class="grid gap-4 xl:grid-cols-2">
        <article v-for="row in filtered" :key="row.id" :aria-label="row.name" class="min-w-0">
          <el-card shadow="never">
            <div class="flex gap-3 items-start justify-between">
              <div class="min-w-0">
                <h2 class="font-semibold break-words">{{ row.name }}</h2>
                <p class="text-sm text-muted-foreground break-words mt-1">{{ row.keyword }}</p>
              </div>
              <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? 'Enabled' : 'Disabled' }}</el-tag>
            </div>
            <p class="text-sm mt-4 break-words">{{ row.asins.join(', ') }}</p>
            <p class="text-sm text-muted-foreground mt-2">{{ row.geo_profile_ids.length }} regions · {{ row.provider_mode }} · depth {{ row.search_depth }}</p>
            <p class="text-sm text-muted-foreground mt-1 break-words">{{ frequency(row) }}</p>
            <p class="text-xs text-muted-foreground mt-1">Auto strict: {{ policyLabel(row) }}</p>
            <div class="flex flex-wrap gap-2 mt-4 monitor-actions">
              <el-button v-if="canWrite" type="primary" :loading="busy.includes(row.id)" :disabled="!row.enabled || !!loadError" @click="run(row)">Run now</el-button>
              <el-button @click="results(row)">Results</el-button>
              <el-button v-if="canWrite" :disabled="loading || !!loadError" @click="openEditor(row)">Edit</el-button>
              <el-dropdown v-if="canWrite" trigger="click" @command="command => more(command, row)">
                <el-button :disabled="busy.includes(row.id)">More</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="alerts">Alerts</el-dropdown-item>
                    <el-dropdown-item command="policy">Verification policy</el-dropdown-item>
                    <el-dropdown-item v-if="row.provider_mode === 'managed'" command="verify" :disabled="!row.enabled">Verify now</el-dropdown-item>
                    <el-dropdown-item command="toggle" divided>{{ row.enabled ? 'Disable' : 'Enable' }}</el-dropdown-item>
                    <el-dropdown-item command="delete">Delete</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </el-card>
        </article>
      </div>
    </div>

    <MonitorEditor v-model="dialog" :monitor="editing" :geos="geos" @saved="saved" />
    <MonitorActivity v-model="activityOpen" :monitor="activityMonitor" :queued-job="queuedJob" />

    <el-dialog
      v-model="policyDialog"
      title="Auto strict verification"
      width="min(560px, 92vw)"
    >
      <template v-if="policyMonitor">
        <div class="text-sm text-muted-foreground mb-4">
          Configure anomaly and low-confidence strict recovery for
          <span class="font-medium text-foreground">{{ policyMonitor.name }}</span>.
        </div>
        <el-form label-position="top">
          <el-form-item label="Policy">
            <el-select v-model="policyForm.mode" class="w-full">
              <el-option label="Inherit workspace default" value="inherit" />
              <el-option label="On for this monitor" value="on" />
              <el-option label="Off for this monitor" value="off" />
            </el-select>
          </el-form-item>
          <el-form-item
            v-if="policyForm.mode !== 'inherit'"
            label="Minimum confidence"
          >
            <div class="flex items-center gap-2">
              <el-input-number
                v-model="policyForm.minConfidence"
                :min="1"
                :max="100"
                :step="5"
              />
              <span class="text-sm text-muted-foreground">%</span>
            </div>
          </el-form-item>
          <el-form-item
            v-if="policyForm.mode !== 'inherit'"
            label="Max paid strict probes / run"
          >
            <el-input-number
              v-model="policyForm.maxProbes"
              :min="0"
              :max="100"
            />
            <div class="text-xs text-muted-foreground mt-1">
              0 keeps strict cache reuse enabled but blocks new strict browser probes.
            </div>
          </el-form-item>
          <el-alert
            v-if="policyForm.mode === 'inherit'"
            type="info"
            :closable="false"
            title="This monitor will use the workspace/runtime Auto Strict policy."
          />
          <el-alert
            v-else-if="policyForm.mode === 'on'"
            type="warning"
            :closable="false"
            title="The runtime Auto Strict kill switch must also be enabled."
          />
        </el-form>
      </template>
      <template #footer>
        <el-button @click="policyDialog = false">Cancel</el-button>
        <el-button
          type="primary"
          :loading="policySubmitting"
          @click="savePolicy"
        >
          Save policy
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.monitor-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
