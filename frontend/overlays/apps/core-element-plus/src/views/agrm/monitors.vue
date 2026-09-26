<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi, type GeoProfile, type Monitor } from '@/api/agrm'

defineOptions({ name: 'Monitors' })

const router = useRouter()
const loading = ref(false)
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const dialog = ref(false)
const submitting = ref(false)
const policyDialog = ref(false)
const policySubmitting = ref(false)
const policyMonitor = ref<Monitor | null>(null)
const form = reactive({
  name: '',
  marketplace: 'amazon.com',
  keyword: '',
  asinsText: '',
  geo_profile_ids: [] as string[],
  search_depth: 100,
  provider_mode: 'managed' as 'managed' | 'strict',
  auto_strict_mode: 'inherit' as 'inherit' | 'on' | 'off',
  auto_strict_min_confidence: 75,
  auto_strict_max_probes_per_run: 3,
  schedule: '',
})
const policyForm = reactive({
  mode: 'inherit' as 'inherit' | 'on' | 'off',
  minConfidence: 75,
  maxProbes: 3,
})

async function load() {
  loading.value = true
  try {
    const [monitorData, geoData] = await Promise.all([
      agrmApi.getMonitors(),
      agrmApi.getGeoProfiles(),
    ])
    monitors.value = monitorData
    geos.value = geoData
  }
  finally {
    loading.value = false
  }
}

function resetForm() {
  Object.assign(form, {
    name: '',
    marketplace: 'amazon.com',
    keyword: '',
    asinsText: '',
    geo_profile_ids: [],
    search_depth: 100,
    provider_mode: 'managed',
    auto_strict_mode: 'inherit',
    auto_strict_min_confidence: 75,
    auto_strict_max_probes_per_run: 3,
    schedule: '',
  })
}

async function create() {
  const asins = form.asinsText
    .split(/[\n,\s]+/)
    .map(item => item.trim().toUpperCase())
    .filter(Boolean)
  if (!form.name.trim() || !form.keyword.trim() || !asins.length || !form.geo_profile_ids.length) {
    ElMessage.warning('Name, keyword, ASINs and geo profiles are required')
    return
  }
  submitting.value = true
  try {
    await agrmApi.createMonitor({
      name: form.name.trim(),
      marketplace: form.marketplace,
      keyword: form.keyword.trim(),
      asins,
      geo_profile_ids: form.geo_profile_ids,
      search_depth: form.search_depth,
      provider_mode: form.provider_mode,
      auto_strict_enabled: (
        form.auto_strict_mode === 'inherit'
          ? null
          : form.auto_strict_mode === 'on'
      ),
      auto_strict_min_confidence: (
        form.auto_strict_mode === 'inherit'
          ? null
          : form.auto_strict_min_confidence / 100
      ),
      auto_strict_max_probes_per_run: (
        form.auto_strict_mode === 'inherit'
          ? null
          : form.auto_strict_max_probes_per_run
      ),
      schedule: form.schedule.trim() || null,
    })
    ElMessage.success('Monitor created')
    dialog.value = false
    resetForm()
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to create monitor')
  }
  finally {
    submitting.value = false
  }
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
      { type: 'warning', confirmButtonText: 'Delete' },
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

async function run(row: any, forceStrict = false) {
  try {
    const monitor = row as Monitor
    if (forceStrict) {
      await ElMessageBox.confirm(
        'Force strict browser verification for this run? Strict probes can consume additional credits and remain subject to the configured per-run probe budget.',
        'Force strict verification',
        { type: 'warning', confirmButtonText: 'Queue verified run' },
      )
    }
    const job: any = await agrmApi.runMonitor(monitor.id, forceStrict)
    ElMessage.success(
      (forceStrict ? 'Verified run queued: ' : 'Run queued: ') + job.id,
    )
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to queue monitor')
  }
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
      <el-button type="primary" @click="dialog = true">Create monitor</el-button>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="monitors" empty-text="No monitors yet">
        <el-table-column prop="name" label="Monitor" min-width="170" />
        <el-table-column prop="keyword" label="Keyword" min-width="180" />
        <el-table-column label="ASINs" width="90">
          <template #default="{ row }">{{ row.asins.length }}</template>
        </el-table-column>
        <el-table-column label="Geos" width="90">
          <template #default="{ row }">{{ row.geo_profile_ids.length }}</template>
        </el-table-column>
        <el-table-column prop="provider_mode" label="Mode" width="110">
          <template #default="{ row }">
            <el-tag :type="row.provider_mode === 'strict' ? 'warning' : 'info'">{{ row.provider_mode }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Auto strict" width="190">
          <template #default="{ row }">
            <el-tag
              :type="policyMode(row as Monitor) === 'on'
                ? 'success'
                : policyMode(row as Monitor) === 'off'
                  ? 'info'
                  : 'warning'"
              size="small"
            >
              {{ policyLabel(row as Monitor) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="search_depth" label="Depth" width="90" />
        <el-table-column prop="schedule" label="Schedule" min-width="150">
          <template #default="{ row }">{{ row.schedule || 'Manual' }}</template>
        </el-table-column>
        <el-table-column label="Status" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? 'Enabled' : 'Disabled' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Actions" width="470" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :disabled="!row.enabled" @click="run(row)">Run now</el-button>
            <el-button
              v-if="row.provider_mode === 'managed'"
              size="small"
              type="warning"
              plain
              :disabled="!row.enabled"
              @click="run(row, true)"
            >
              Verify now
            </el-button>
            <el-button size="small" @click="openAlerts(row as Monitor)">Alerts</el-button>
            <el-button size="small" @click="openPolicy(row as Monitor)">Verify</el-button>
            <el-button size="small" @click="toggleEnabled(row as Monitor)">{{ row.enabled ? 'Disable' : 'Enable' }}</el-button>
            <el-button size="small" type="danger" text @click="remove(row as Monitor)">Delete</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" title="Create monitor" width="min(680px, 92vw)" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="Name">
          <el-input v-model="form.name" placeholder="Walking Pad · US" />
        </el-form-item>
        <div class="grid gap-x-4 md:grid-cols-2">
          <el-form-item label="Marketplace">
            <el-select v-model="form.marketplace" class="w-full">
              <el-option label="Amazon.com (US)" value="amazon.com" />
            </el-select>
          </el-form-item>
          <el-form-item label="Provider">
            <el-select v-model="form.provider_mode" class="w-full">
              <el-option label="Managed" value="managed" />
              <el-option label="Strict verify" value="strict" />
            </el-select>
          </el-form-item>
        </div>
        <div
          v-if="form.provider_mode === 'managed'"
          class="grid gap-x-4 md:grid-cols-2"
        >
          <el-form-item label="Auto strict verification">
            <el-select v-model="form.auto_strict_mode" class="w-full">
              <el-option label="Inherit workspace default" value="inherit" />
              <el-option label="On for this monitor" value="on" />
              <el-option label="Off for this monitor" value="off" />
            </el-select>
          </el-form-item>
          <el-form-item
            v-if="form.auto_strict_mode !== 'inherit'"
            label="Minimum confidence"
          >
            <el-input-number
              v-model="form.auto_strict_min_confidence"
              :min="1"
              :max="100"
              :step="5"
            />
            <span class="ml-2 text-xs text-muted-foreground">%</span>
          </el-form-item>
          <el-form-item
            v-if="form.auto_strict_mode !== 'inherit'"
            label="Max paid strict probes / run"
          >
            <el-input-number
              v-model="form.auto_strict_max_probes_per_run"
              :min="0"
              :max="100"
            />
          </el-form-item>
        </div>
        <el-form-item label="Keyword">
          <el-input v-model="form.keyword" placeholder="walking pad" />
        </el-form-item>
        <el-form-item label="ASINs">
          <el-input v-model="form.asinsText" type="textarea" :rows="3" placeholder="One ASIN per line" />
        </el-form-item>
        <el-form-item label="Geo Profiles">
          <el-select v-model="form.geo_profile_ids" multiple class="w-full" placeholder="Select geographies">
            <el-option
              v-for="geo in geos"
              :key="geo.id"
              :label="geo.name + ' · ' + geo.delivery_postal_code"
              :value="geo.id"
            />
          </el-select>
        </el-form-item>
        <div class="grid gap-x-4 md:grid-cols-2">
          <el-form-item label="Search depth">
            <el-input-number v-model="form.search_depth" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="Schedule (optional)">
            <el-input v-model="form.schedule" placeholder="UTC cron, e.g. 0 */6 * * *" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">Cancel</el-button>
        <el-button type="primary" :loading="submitting" @click="create">Create</el-button>
      </template>
    </el-dialog>

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
