<script setup lang="ts">
import type {
  CompetitiveSummary,
  CompetitiveTrend,
  GeoProfile,
  Monitor,
} from '@/api/agrm'
import { ElMessage } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'CompetitiveIntelligence' })

const loading = ref(false)
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const selectedMonitorId = ref('')
const hours = ref(168)
const topN = ref(20)
const includeTracked = ref(false)
const summary = ref<CompetitiveSummary>()
const trend = ref<CompetitiveTrend>()

const periodOptions = [
  { label: '24 hours', value: 24 },
  { label: '7 days', value: 168 },
  { label: '30 days', value: 720 },
  { label: '90 days', value: 2160 },
]
const topOptions = [10, 20, 50, 100]

const selectedMonitor = computed(() =>
  monitors.value.find(item => item.id === selectedMonitorId.value),
)

function geoName(id: string) {
  return geos.value.find(item => item.id === id)?.name || id
}

function formatRank(value: number | null | undefined) {
  if (value == null) {
    return '—'
  }
  return `#${Number(value).toFixed(Number(value) % 1 ? 1 : 0)}`
}

function formatPct(value: number | null | undefined) {
  if (value == null) {
    return '—'
  }
  return `${Number(value).toFixed(1)}%`
}

function changeText(value: number | null | undefined) {
  if (value == null) {
    return '—'
  }
  if (value < 0) {
    return `${Math.abs(value).toFixed(1)} better`
  }
  if (value > 0) {
    return `${value.toFixed(1)} worse`
  }
  return 'No change'
}

function changeType(value: number | null | undefined) {
  if (value == null || value === 0) {
    return 'info'
  }
  return value < 0 ? 'success' : 'danger'
}

function seriesFor(asin: string) {
  return (trend.value?.series || []).filter(item => item.asin === asin)
}

function sparklinePoints(asin: string) {
  const points = seriesFor(asin)
    .filter(item => item.average_organic_rank != null)
  if (!points.length) {
    return ''
  }
  const values = points.map(item => Number(item.average_organic_rank))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const width = 260
  const height = 72
  const padding = 6
  const range = Math.max(max - min, 1)
  return values
    .map((value, index) => {
      const x = values.length === 1
        ? width / 2
        : padding + (index * (width - padding * 2)) / (values.length - 1)
      const y = padding + ((value - min) / range) * (height - padding * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

async function loadIntelligence() {
  if (!selectedMonitorId.value) {
    summary.value = undefined
    trend.value = undefined
    return
  }
  loading.value = true
  try {
    const data = await agrmApi.getCompetitiveSummary(
      selectedMonitorId.value,
      hours.value,
      topN.value,
      100,
      includeTracked.value,
    )
    summary.value = data
    const asins = data.competitors.slice(0, 8).map(item => item.asin)
    trend.value = asins.length
      ? await agrmApi.getCompetitiveTrend(
          selectedMonitorId.value,
          hours.value,
          topN.value,
          asins,
        )
      : undefined
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load competitor intelligence')
  }
  finally {
    loading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [monitorData, geoData] = await Promise.all([
      agrmApi.getMonitors(),
      agrmApi.getGeoProfiles(),
    ])
    monitors.value = monitorData
    geos.value = geoData
    if (!selectedMonitorId.value && monitorData.length) {
      selectedMonitorId.value = monitorData[0].id
    }
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load monitors')
  }
  finally {
    loading.value = false
  }
  await loadIntelligence()
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">
        SERP competitive intelligence
      </div>
      <h1 class="text-2xl font-semibold mt-1">Competitor Intelligence</h1>
      <p class="text-sm text-muted-foreground mt-1">
        Discover which ASINs own organic and sponsored visibility across your monitored geographies.
      </p>
    </div>

    <el-card shadow="never">
      <div class="grid gap-4 lg:grid-cols-[minmax(240px,1fr)_150px_140px_auto_auto] items-end">
        <el-form-item label="Monitor" class="!mb-0">
          <el-select v-model="selectedMonitorId" class="w-full" @change="loadIntelligence">
            <el-option
              v-for="monitor in monitors"
              :key="monitor.id"
              :label="`${monitor.name} · ${monitor.keyword}`"
              :value="monitor.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="Window" class="!mb-0">
          <el-select v-model="hours" class="w-full" @change="loadIntelligence">
            <el-option
              v-for="option in periodOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="SERP depth" class="!mb-0">
          <el-select v-model="topN" class="w-full" @change="loadIntelligence">
            <el-option
              v-for="value in topOptions"
              :key="value"
              :label="`Top ${value}`"
              :value="value"
            />
          </el-select>
        </el-form-item>

        <el-checkbox v-model="includeTracked" @change="loadIntelligence">
          Include tracked ASINs
        </el-checkbox>

        <el-button :loading="loading" @click="loadIntelligence">Refresh</el-button>
      </div>
    </el-card>

    <el-alert
      v-if="selectedMonitorId && summary && !summary.probe_count"
      type="info"
      :closable="false"
      title="No competitive SERP history yet"
      description="Run this monitor again after Phase 20 deployment. Competitive intelligence starts from newly captured SERP probes."
    />

    <div v-if="summary?.probe_count" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <el-card shadow="never">
        <div class="text-xs text-muted-foreground uppercase tracking-wider">Discovered ASINs</div>
        <div class="text-3xl font-semibold mt-2">{{ summary.competitors.length }}</div>
        <div class="text-xs text-muted-foreground mt-1">
          {{ includeTracked ? 'Including tracked products' : 'Competitors only' }}
        </div>
      </el-card>
      <el-card shadow="never">
        <div class="text-xs text-muted-foreground uppercase tracking-wider">Geo probes</div>
        <div class="text-3xl font-semibold mt-2">{{ summary.probe_count }}</div>
        <div class="text-xs text-muted-foreground mt-1">
          {{ selectedMonitor?.keyword }}
        </div>
      </el-card>
      <el-card shadow="never">
        <div class="text-xs text-muted-foreground uppercase tracking-wider">Organic slots</div>
        <div class="text-3xl font-semibold mt-2">{{ summary.organic_slot_count }}</div>
        <div class="text-xs text-muted-foreground mt-1">Captured inside Top {{ topN }}</div>
      </el-card>
      <el-card shadow="never">
        <div class="text-xs text-muted-foreground uppercase tracking-wider">Sponsored slots</div>
        <div class="text-3xl font-semibold mt-2">{{ summary.sponsored_slot_count }}</div>
        <div class="text-xs text-muted-foreground mt-1">Captured inside Top {{ topN }}</div>
      </el-card>
    </div>

    <el-card v-if="summary?.competitors.length" v-loading="loading" shadow="never">
      <template #header>
        <div>
          <div class="font-medium">SERP visibility leaders</div>
          <div class="text-xs text-muted-foreground mt-1">
            Organic SOV is the ASIN's share of all captured Top {{ topN }} organic slots.
            Coverage is the share of geo probes where it appeared.
          </div>
        </div>
      </template>

      <el-table :data="summary.competitors" stripe>
        <el-table-column label="Product" min-width="270" fixed="left">
          <template #default="{ row }">
            <div class="flex items-center gap-2">
              <span class="font-mono text-xs">{{ row.asin }}</span>
              <el-tag v-if="row.tracked" type="info" size="small">Tracked</el-tag>
            </div>
            <div class="text-xs text-muted-foreground mt-1 line-clamp-2">
              {{ row.title || 'No title captured' }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Organic SOV" width="130" sortable prop="organic_sov_pct">
          <template #default="{ row }">
            <div class="font-semibold">{{ formatPct(row.organic_sov_pct) }}</div>
            <el-progress
              :percentage="Math.min(row.organic_sov_pct, 100)"
              :show-text="false"
              :stroke-width="5"
              class="mt-1"
            />
          </template>
        </el-table-column>

        <el-table-column label="Geo coverage" width="125" sortable prop="organic_probe_coverage_pct">
          <template #default="{ row }">
            {{ formatPct(row.organic_probe_coverage_pct) }}
          </template>
        </el-table-column>

        <el-table-column label="Avg organic" width="115" sortable prop="average_organic_rank">
          <template #default="{ row }">{{ formatRank(row.average_organic_rank) }}</template>
        </el-table-column>

        <el-table-column label="Best" width="85" prop="best_organic_rank">
          <template #default="{ row }">{{ formatRank(row.best_organic_rank) }}</template>
        </el-table-column>

        <el-table-column label="Latest" width="90" prop="latest_organic_rank">
          <template #default="{ row }">{{ formatRank(row.latest_organic_rank) }}</template>
        </el-table-column>

        <el-table-column label="Change" width="125">
          <template #default="{ row }">
            <el-tag :type="changeType(row.organic_rank_change)" size="small">
              {{ changeText(row.organic_rank_change) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="Sponsored SOV" width="135" sortable prop="sponsored_sov_pct">
          <template #default="{ row }">{{ formatPct(row.sponsored_sov_pct) }}</template>
        </el-table-column>

        <el-table-column label="Trend" min-width="200">
          <template #default="{ row }">
            <svg
              viewBox="0 0 260 72"
              class="w-56 h-16"
              role="img"
              :aria-label="`${row.asin} competitor rank trend`"
            >
              <polyline
                v-if="sparklinePoints(row.asin)"
                :points="sparklinePoints(row.asin)"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                vector-effect="non-scaling-stroke"
              />
            </svg>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="summary?.geo_leaders.length" shadow="never">
      <template #header>
        <div>
          <div class="font-medium">Geographic leaders</div>
          <div class="text-xs text-muted-foreground mt-1">
            Top competitors by repeated organic presence in each configured Geo Profile.
          </div>
        </div>
      </template>

      <div class="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="geo in summary.geo_leaders"
          :key="geo.geo_profile_id"
          class="border rounded-lg p-4"
        >
          <div class="font-medium">{{ geoName(geo.geo_profile_id) }}</div>
          <div class="text-xs text-muted-foreground mb-3">{{ geo.geo_profile_id }}</div>

          <div v-for="(leader, index) in geo.leaders" :key="leader.asin" class="flex items-center gap-3 py-2 border-t first:border-t-0">
            <div class="text-xs text-muted-foreground w-5">{{ index + 1 }}</div>
            <div class="min-w-0 flex-1">
              <div class="font-mono text-xs">{{ leader.asin }}</div>
              <div class="text-xs text-muted-foreground">
                {{ leader.appearances }} appearances · avg {{ formatRank(leader.average_organic_rank) }}
              </div>
            </div>
            <el-tag size="small">Best {{ formatRank(leader.best_organic_rank) }}</el-tag>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>
