<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi, type GeoProfile, type Monitor } from '@/api/agrm'

defineOptions({ name: 'Monitors' })

const loading = ref(false)
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const dialog = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  marketplace: 'amazon.com',
  keyword: '',
  asinsText: '',
  geo_profile_ids: [] as string[],
  search_depth: 100,
  provider_mode: 'managed' as 'managed' | 'strict',
  schedule: '',
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

async function run(row: Monitor) {
  try {
    const job: any = await agrmApi.runMonitor(row.id)
    ElMessage.success('Run queued: ' + job.id)
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
        <el-table-column prop="search_depth" label="Depth" width="90" />
        <el-table-column prop="schedule" label="Schedule" min-width="150">
          <template #default="{ row }">{{ row.schedule || 'Manual' }}</template>
        </el-table-column>
        <el-table-column label="Actions" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="run(row)">Run now</el-button>
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
            <el-input v-model="form.schedule" placeholder="e.g. 0 */6 * * *" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">Cancel</el-button>
        <el-button type="primary" :loading="submitting" @click="create">Create</el-button>
      </template>
    </el-dialog>
  </div>
</template>
