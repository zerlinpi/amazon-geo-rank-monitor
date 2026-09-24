<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'Dashboard' })

const loading = ref(true)
const credits = ref({ balance: 0, reserved: 0, available: 0 })
const monitors = ref<any[]>([])
const geos = ref<any[]>([])
const runs = ref<any[]>([])

const successfulRuns = computed(() => runs.value.filter(run => run.status === 'succeeded').length)
const probeCount = computed(() => runs.value.reduce((sum, run) => sum + (run.settled_probe_count || 0), 0))

async function load() {
  loading.value = true
  try {
    const [creditData, monitorData, geoData, runData] = await Promise.all([
      agrmApi.getCredits(),
      agrmApi.getMonitors(),
      agrmApi.getGeoProfiles(),
      agrmApi.getRuns(10),
    ])
    credits.value = creditData as any
    monitors.value = monitorData as any[]
    geos.value = geoData as any[]
    runs.value = runData as any[]
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load dashboard')
  }
  finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5" v-loading="loading">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">
          Amazon Geographic Rank
        </div>
        <h1 class="text-2xl font-semibold mt-1">
          Dashboard
        </h1>
        <p class="text-sm text-muted-foreground mt-1">
          Weighted organic rank monitoring across geographic contexts.
        </p>
      </div>
      <FaButton @click="$router.push('/ranking/explorer')">
        <FaIcon name="i-lucide:search" class="mr-2" />
        New rank check
      </FaButton>
    </div>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <el-card shadow="never">
        <el-statistic title="Available credits" :value="credits.available" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="Active monitors" :value="monitors.length" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="Geo profiles" :value="geos.length" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="Recent probes" :value="probeCount" />
      </el-card>
    </div>

    <div class="grid gap-4 xl:grid-cols-[2fr_1fr]">
      <el-card shadow="never">
        <template #header>
          <div class="flex justify-between items-center">
            <span class="font-medium">Recent rank runs</span>
            <el-button text @click="$router.push('/ranking/history')">
              View all
            </el-button>
          </div>
        </template>
        <el-table :data="runs" empty-text="No rank runs yet">
          <el-table-column prop="keyword" label="Keyword" min-width="180" />
          <el-table-column prop="marketplace" label="Marketplace" width="130" />
          <el-table-column label="Status" width="150">
            <template #default="{ row }">
              <el-tag :type="row.status === 'succeeded' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Probes" width="100">
            <template #default="{ row }">
              {{ row.settled_probe_count }}/{{ row.requested_probe_count }}
            </template>
          </el-table-column>
          <el-table-column label="Started" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.started_at).toLocaleString() }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span class="font-medium">System snapshot</span>
        </template>
        <div class="space-y-5">
          <div>
            <div class="text-sm text-muted-foreground">
              Successful recent runs
            </div>
            <div class="text-3xl font-semibold mt-1">
              {{ successfulRuns }}/{{ runs.length }}
            </div>
          </div>
          <el-progress :percentage="runs.length ? Math.round(successfulRuns / runs.length * 100) : 0" />
          <el-divider />
          <div class="text-sm text-muted-foreground">
            Reserved credits
          </div>
          <div class="text-xl font-semibold">
            {{ credits.reserved }}
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>
