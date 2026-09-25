<script setup lang="ts">
import type {
  AnalyticsSummary,
  AnalyticsTrend,
  GeoProfile,
  Monitor,
  ReportDelivery,
  ReportSchedule,
  ReportSchedulePayload,
} from '@/api/agrm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'AnalyticsReports' })

const loading = ref(false)
const reportsLoading = ref(false)
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const selectedMonitorId = ref('')
const hours = ref(168)
const trend = ref<AnalyticsTrend>()
const summary = ref<AnalyticsSummary>()

const reportSchedules = ref<ReportSchedule[]>([])
const reportDeliveries = ref<ReportDelivery[]>([])
const reportsAvailable = ref(true)
const reportDialog = ref(false)
const editingReportId = ref<string | null>(null)
const savingReport = ref(false)
const sendingReportId = ref<string | null>(null)

const reportForm = reactive({
  name: '',
  monitor_target_ids: [] as string[],
  recipientsText: '',
  schedule: '0 9 * * 1',
  lookback_hours: 168,
  include_csv: true,
  enabled: true,
})

const periodOptions = [
  { label: '24 hours', value: 24 },
  { label: '7 days', value: 168 },
  { label: '30 days', value: 720 },
  { label: '90 days', value: 2160 },
  { label: '1 year', value: 8760 },
]

const selectedMonitor = computed(() =>
  monitors.value.find(item => item.id === selectedMonitorId.value),
)

function monitorName(id: string) {
  return monitors.value.find(item => item.id === id)?.name || id
}

function reportMonitorNames(ids: string[]) {
  return ids.map(id => monitorName(id)).join(', ')
}

function geoName(id: string) {
  return geos.value.find(item => item.id === id)?.name || id
}

function formatRank(value: string | number | null | undefined) {
  if (value == null) {
    return '—'
  }
  return `#${Number(value).toFixed(Number(value) % 1 ? 1 : 0)}`
}

function formatPercent(value: string | number | null | undefined) {
  if (value == null) {
    return '—'
  }
  return `${(Number(value) * 100).toFixed(1)}%`
}

function changeText(value: string | number) {
  const numeric = Number(value)
  if (numeric < 0) {
    return `${Math.abs(numeric).toFixed(1)} better`
  }
  if (numeric > 0) {
    return `${numeric.toFixed(1)} worse`
  }
  return 'No change'
}

function changeTagType(value: string | number) {
  const numeric = Number(value)
  if (numeric < 0) {
    return 'success'
  }
  if (numeric > 0) {
    return 'danger'
  }
  return 'info'
}

function aggregatePoints(asin: string) {
  return (trend.value?.aggregate || []).filter(item => item.asin === asin)
}

function sparklinePoints(asin: string) {
  const points = aggregatePoints(asin)
  if (!points.length) {
    return ''
  }
  const values = points.map(item => Number(item.weighted_rank))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const width = 320
  const height = 90
  const padding = 8
  const range = Math.max(max - min, 1)
  return values
    .map((value, index) => {
      const x = points.length === 1
        ? width / 2
        : padding + (index * (width - padding * 2)) / (points.length - 1)
      const y = padding + ((value - min) / range) * (height - padding * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

async function loadAnalytics() {
  if (!selectedMonitorId.value) {
    trend.value = undefined
    summary.value = undefined
    return
  }
  loading.value = true
  try {
    const [trendData, summaryData] = await Promise.all([
      agrmApi.getMonitorTrend(selectedMonitorId.value, hours.value),
      agrmApi.getMonitorAnalyticsSummary(selectedMonitorId.value, hours.value),
    ])
    trend.value = trendData
    summary.value = summaryData
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load analytics')
  }
  finally {
    loading.value = false
  }
}

async function loadReports() {
  reportsLoading.value = true
  try {
    const [schedules, deliveries] = await Promise.all([
      agrmApi.getReportSchedules(),
      agrmApi.getReportDeliveries(100),
    ])
    reportSchedules.value = schedules
    reportDeliveries.value = deliveries
    reportsAvailable.value = true
  }
  catch (error: any) {
    if (error.response?.status === 403) {
      reportsAvailable.value = false
      reportSchedules.value = []
      reportDeliveries.value = []
    }
    else {
      ElMessage.error(error.response?.data?.detail || 'Failed to load reports')
    }
  }
  finally {
    reportsLoading.value = false
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
  finally {
    loading.value = false
  }
  await Promise.all([loadAnalytics(), loadReports()])
}

async function downloadCsv(granularity: 'aggregate' | 'geo') {
  if (!selectedMonitorId.value) {
    return
  }
  try {
    const blob = await agrmApi.exportMonitorCsv(
      selectedMonitorId.value,
      hours.value,
      granularity,
    )
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    const monitor = selectedMonitor.value?.name || 'monitor'
    anchor.href = url
    anchor.download = `${monitor}-${granularity}-${hours.value}h.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'CSV export failed')
  }
}

function resetReportForm() {
  Object.assign(reportForm, {
    name: '',
    monitor_target_ids: selectedMonitorId.value
      ? [selectedMonitorId.value]
      : [],
    recipientsText: '',
    schedule: '0 9 * * 1',
    lookback_hours: hours.value,
    include_csv: true,
    enabled: true,
  })
  editingReportId.value = null
}

function openCreateReport() {
  resetReportForm()
  reportDialog.value = true
}

function openEditReport(row: ReportSchedule) {
  editingReportId.value = row.id
  Object.assign(reportForm, {
    name: row.name,
    monitor_target_ids: [...row.monitor_target_ids],
    recipientsText: row.recipients.join('\n'),
    schedule: row.schedule,
    lookback_hours: row.lookback_hours,
    include_csv: row.include_csv,
    enabled: row.enabled,
  })
  reportDialog.value = true
}

function reportRecipients() {
  return reportForm.recipientsText
    .split(/[\n,;]+/)
    .map(item => item.trim().toLowerCase())
    .filter(Boolean)
}

async function saveReport() {
  const recipients = reportRecipients()
  if (
    !reportForm.name.trim()
    || !reportForm.monitor_target_ids.length
    || !recipients.length
    || !reportForm.schedule.trim()
  ) {
    ElMessage.warning('Name, monitor, recipient and schedule are required')
    return
  }
  const payload: ReportSchedulePayload = {
    name: reportForm.name.trim(),
    monitor_target_ids: reportForm.monitor_target_ids,
    recipients,
    schedule: reportForm.schedule.trim(),
    lookback_hours: reportForm.lookback_hours,
    include_csv: reportForm.include_csv,
    enabled: reportForm.enabled,
  }
  savingReport.value = true
  try {
    if (editingReportId.value) {
      await agrmApi.updateReportSchedule(editingReportId.value, payload)
      ElMessage.success('Report schedule updated')
    }
    else {
      await agrmApi.createReportSchedule(payload)
      ElMessage.success('Report schedule created')
    }
    reportDialog.value = false
    await loadReports()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to save report')
  }
  finally {
    savingReport.value = false
  }
}

async function toggleReport(row: ReportSchedule) {
  try {
    await agrmApi.updateReportSchedule(row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? 'Report disabled' : 'Report enabled')
    await loadReports()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update report')
  }
}

async function sendReport(row: ReportSchedule) {
  sendingReportId.value = row.id
  try {
    const delivery = await agrmApi.sendReportNow(row.id)
    if (delivery.status === 'sent') {
      ElMessage.success('Report sent')
    }
    else {
      ElMessage.warning(`Report finished with status: ${delivery.status}`)
    }
    await loadReports()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to send report')
  }
  finally {
    sendingReportId.value = null
  }
}

async function archiveReport(row: ReportSchedule) {
  try {
    await ElMessageBox.confirm(
      `Archive report schedule "${row.name}"? Delivery history will remain.`,
      'Archive report',
      { type: 'warning', confirmButtonText: 'Archive' },
    )
    await agrmApi.deleteReportSchedule(row.id)
    ElMessage.success('Report schedule archived')
    await loadReports()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to archive report')
  }
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">
          Historical intelligence
        </div>
        <h1 class="text-2xl font-semibold mt-1">Analytics & Reports</h1>
        <p class="text-sm text-muted-foreground mt-1">
          Compare rank trends, geographic performance and scheduled stakeholder reports.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <el-button :disabled="!selectedMonitorId" @click="downloadCsv('aggregate')">
          Export aggregate CSV
        </el-button>
        <el-button :disabled="!selectedMonitorId" @click="downloadCsv('geo')">
          Export geo CSV
        </el-button>
      </div>
    </div>

    <el-card shadow="never">
      <div class="grid gap-4 md:grid-cols-[minmax(240px,1fr)_180px_auto] items-end">
        <el-form-item label="Monitor" class="!mb-0">
          <el-select v-model="selectedMonitorId" class="w-full" @change="loadAnalytics">
            <el-option
              v-for="monitor in monitors"
              :key="monitor.id"
              :label="`${monitor.name} · ${monitor.keyword}`"
              :value="monitor.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Window" class="!mb-0">
          <el-select v-model="hours" class="w-full" @change="loadAnalytics">
            <el-option
              v-for="option in periodOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-button :loading="loading" @click="loadAnalytics">Refresh</el-button>
      </div>
    </el-card>

    <el-alert
      v-if="selectedMonitorId && summary && !summary.run_count"
      type="info"
      :closable="false"
      title="No completed runs in this window"
      description="Run the monitor or choose a larger time window."
    />

    <div v-if="summary?.asins.length" class="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
      <el-card v-for="item in summary.asins" :key="item.asin" shadow="never">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="font-mono text-xs text-muted-foreground">{{ item.asin }}</div>
            <div class="text-3xl font-semibold mt-1">{{ formatRank(item.latest_rank) }}</div>
          </div>
          <el-tag :type="changeTagType(item.change)">
            {{ changeText(item.change) }}
          </el-tag>
        </div>

        <svg
          viewBox="0 0 320 90"
          class="w-full h-24 mt-4"
          role="img"
          :aria-label="`${item.asin} rank trend`"
        >
          <polyline
            :points="sparklinePoints(item.asin)"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>

        <div class="grid grid-cols-2 gap-3 text-xs mt-3">
          <div>
            <div class="text-muted-foreground">Best</div>
            <div class="font-medium mt-1">{{ formatRank(item.best_rank) }}</div>
          </div>
          <div>
            <div class="text-muted-foreground">Worst</div>
            <div class="font-medium mt-1">{{ formatRank(item.worst_rank) }}</div>
          </div>
          <div>
            <div class="text-muted-foreground">Average</div>
            <div class="font-medium mt-1">{{ formatRank(item.average_rank) }}</div>
          </div>
          <div>
            <div class="text-muted-foreground">Found rate</div>
            <div class="font-medium mt-1">{{ formatPercent(item.average_found_rate) }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="flex items-center justify-between gap-3">
          <span class="font-medium">Geographic performance</span>
          <span class="text-xs text-muted-foreground">
            {{ summary?.run_count || 0 }} completed runs
          </span>
        </div>
      </template>
      <el-table :data="summary?.geos || []" empty-text="No geographic observations">
        <el-table-column prop="asin" label="ASIN" min-width="130" />
        <el-table-column label="Geo" min-width="160">
          <template #default="{ row }">{{ geoName(row.geo_profile_id) }}</template>
        </el-table-column>
        <el-table-column label="Avg rank" width="110">
          <template #default="{ row }">{{ formatRank(row.average_effective_rank) }}</template>
        </el-table-column>
        <el-table-column label="Best" width="100">
          <template #default="{ row }">{{ formatRank(row.best_effective_rank) }}</template>
        </el-table-column>
        <el-table-column label="Worst" width="100">
          <template #default="{ row }">{{ formatRank(row.worst_effective_rank) }}</template>
        </el-table-column>
        <el-table-column label="Found" width="110">
          <template #default="{ row }">{{ formatPercent(row.found_rate) }}</template>
        </el-table-column>
        <el-table-column prop="observation_count" label="Observations" width="120" />
      </el-table>
    </el-card>

    <el-alert
      v-if="!reportsAvailable"
      type="info"
      :closable="false"
      title="Scheduled reports require Admin access"
      description="Historical analytics and CSV export remain available with rank read access."
    />

    <template v-else>
      <el-card shadow="never" v-loading="reportsLoading">
        <template #header>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span class="font-medium">Scheduled reports</span>
              <div class="text-xs text-muted-foreground mt-1">
                Five-field cron schedules are interpreted in UTC.
              </div>
            </div>
            <el-button type="primary" @click="openCreateReport">Create report</el-button>
          </div>
        </template>
        <el-table :data="reportSchedules" empty-text="No report schedules">
          <el-table-column prop="name" label="Report" min-width="180" />
          <el-table-column label="Monitors" min-width="190">
            <template #default="{ row }">
              {{ reportMonitorNames(row.monitor_target_ids) }}
            </template>
          </el-table-column>
          <el-table-column prop="schedule" label="UTC cron" min-width="130" />
          <el-table-column label="Window" width="100">
            <template #default="{ row }">{{ row.lookback_hours }}h</template>
          </el-table-column>
          <el-table-column label="Recipients" width="105">
            <template #default="{ row }">{{ row.recipients.length }}</template>
          </el-table-column>
          <el-table-column label="CSV" width="80">
            <template #default="{ row }">{{ row.include_csv ? 'Yes' : 'No' }}</template>
          </el-table-column>
          <el-table-column label="Status" width="100">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? 'Enabled' : 'Disabled' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Actions" width="270" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEditReport(row as ReportSchedule)">Edit</el-button>
              <el-button
                size="small"
                :loading="sendingReportId === row.id"
                @click="sendReport(row as ReportSchedule)"
              >
                Send now
              </el-button>
              <el-button size="small" @click="toggleReport(row as ReportSchedule)">
                {{ row.enabled ? 'Disable' : 'Enable' }}
              </el-button>
              <el-button
                size="small"
                type="danger"
                text
                @click="archiveReport(row as ReportSchedule)"
              >
                Archive
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" v-loading="reportsLoading">
        <template #header><span class="font-medium">Report delivery history</span></template>
        <el-table :data="reportDeliveries" empty-text="No report deliveries">
          <el-table-column label="Scheduled" min-width="170">
            <template #default="{ row }">
              {{ new Date(row.scheduled_for).toLocaleString() }}
            </template>
          </el-table-column>
          <el-table-column prop="subject" label="Subject" min-width="230" />
          <el-table-column label="Delivery" width="130">
            <template #default="{ row }">
              {{ row.sent_count }}/{{ row.recipient_count }}
            </template>
          </el-table-column>
          <el-table-column label="Status" width="140">
            <template #default="{ row }">
              <el-tag
                :type="row.status === 'sent' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'"
              >
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="Error" min-width="250" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>

    <el-dialog
      v-model="reportDialog"
      :title="editingReportId ? 'Edit scheduled report' : 'Create scheduled report'"
      width="min(680px, 94vw)"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="Report name">
          <el-input v-model="reportForm.name" placeholder="Weekly rank review" />
        </el-form-item>

        <el-form-item label="Monitors">
          <el-select
            v-model="reportForm.monitor_target_ids"
            multiple
            filterable
            class="w-full"
          >
            <el-option
              v-for="monitor in monitors"
              :key="monitor.id"
              :label="`${monitor.name} · ${monitor.keyword}`"
              :value="monitor.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="Recipients">
          <el-input
            v-model="reportForm.recipientsText"
            type="textarea"
            :rows="3"
            placeholder="ops@example.com&#10;leadership@example.com"
          />
        </el-form-item>

        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item label="UTC cron">
            <el-input v-model="reportForm.schedule" placeholder="0 9 * * 1" />
          </el-form-item>
          <el-form-item label="Lookback">
            <el-select v-model="reportForm.lookback_hours" class="w-full">
              <el-option
                v-for="option in periodOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </div>

        <div class="flex flex-wrap gap-5">
          <el-checkbox v-model="reportForm.include_csv">
            Attach aggregate CSV
          </el-checkbox>
          <el-checkbox v-model="reportForm.enabled">
            Enable schedule
          </el-checkbox>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="reportDialog = false">Cancel</el-button>
        <el-button type="primary" :loading="savingReport" @click="saveReport">
          {{ editingReportId ? 'Save changes' : 'Create report' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
