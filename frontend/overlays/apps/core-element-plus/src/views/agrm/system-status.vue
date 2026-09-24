<script setup lang="ts">
import type { QueueSummary, RankJob, WorkerStatus } from '@/api/agrm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'SystemStatus' })

const loading = ref(false)
const queue = ref<QueueSummary>({ counts: {} })
const workers = ref<WorkerStatus[]>([])
const deadLetters = ref<RankJob[]>([])
let timer: ReturnType<typeof setInterval> | undefined

const pending = computed(() => queue.value.counts.pending || 0)
const running = computed(() => queue.value.counts.running || 0)
const deadLetterCount = computed(() => queue.value.counts.dead_letter || 0)

const oldestPending = computed(() => {
  if (!queue.value.oldest_pending_at) {
    return '—'
  }
  const seconds = Math.max(
    Math.round((Date.now() - new Date(queue.value.oldest_pending_at).getTime()) / 1000),
    0,
  )
  if (seconds < 60) {
    return `${seconds}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`
  }
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
})

function statusType(status: string): 'danger' | 'info' | 'success' | 'warning' {
  if (['error', 'dead_letter'].includes(status)) {
    return 'danger'
  }
  if (['running', 'retry_wait', 'warning'].includes(status)) {
    return 'warning'
  }
  if (['idle', 'succeeded'].includes(status)) {
    return 'success'
  }
  return 'info'
}

async function load(showLoading = true) {
  if (showLoading) {
    loading.value = true
  }
  try {
    const [queueResult, workerResult, deadLetterResult] = await Promise.all([
      agrmApi.getQueueSummary(),
      agrmApi.getSystemWorkers(),
      agrmApi.getDeadLetters(100),
    ])
    queue.value = queueResult
    workers.value = workerResult
    deadLetters.value = deadLetterResult
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load system status')
  }
  finally {
    loading.value = false
  }
}

async function requeue(row: RankJob) {
  try {
    await ElMessageBox.confirm(
      `Requeue dead-letter job ${row.id}? Its attempt counter will be reset.`,
      'Requeue job',
      {
        type: 'warning',
        confirmButtonText: 'Requeue',
      },
    )
    await agrmApi.requeueDeadLetter(row.id)
    ElMessage.success('Job requeued')
    await load(false)
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to requeue job')
  }
}

onMounted(() => {
  void load()
  timer = setInterval(() => void load(false), 10000)
})

onUnmounted(() => {
  if (timer) {
    clearInterval(timer)
  }
})
</script>

<template>
  <div v-loading="loading" class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Operations</div>
        <h1 class="text-2xl font-semibold mt-1">System Status</h1>
        <p class="text-sm text-muted-foreground mt-1">
          Queue health, worker heartbeats, scheduler activity, and dead-letter recovery.
        </p>
      </div>
      <el-button @click="load()">Refresh</el-button>
    </div>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <el-card shadow="never">
        <div class="text-sm text-muted-foreground">Pending</div>
        <div class="text-3xl font-semibold mt-2">{{ pending }}</div>
      </el-card>
      <el-card shadow="never">
        <div class="text-sm text-muted-foreground">Running</div>
        <div class="text-3xl font-semibold mt-2">{{ running }}</div>
      </el-card>
      <el-card shadow="never">
        <div class="text-sm text-muted-foreground">Dead letter</div>
        <div class="text-3xl font-semibold mt-2">{{ deadLetterCount }}</div>
      </el-card>
      <el-card shadow="never">
        <div class="text-sm text-muted-foreground">Oldest pending</div>
        <div class="text-3xl font-semibold mt-2">{{ oldestPending }}</div>
      </el-card>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="font-medium">Workers & schedulers</div>
      </template>
      <el-table :data="workers" empty-text="No heartbeats yet">
        <el-table-column prop="worker_id" label="Instance" min-width="180">
          <template #default="{ row }">
            <span class="font-mono text-xs">{{ row.worker_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="worker_type" label="Type" width="110" />
        <el-table-column label="Status" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="processed_jobs" label="Processed" width="110" />
        <el-table-column label="Last job" min-width="170">
          <template #default="{ row }">
            <span class="font-mono text-xs">{{ row.last_job_id || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Last seen" min-width="170">
          <template #default="{ row }">
            {{ row.last_seen_at ? new Date(row.last_seen_at).toLocaleString() : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="Last error" min-width="220">
          <template #default="{ row }">
            <span class="text-sm">{{ row.last_error || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <div class="font-medium">Dead-letter queue</div>
          <el-tag :type="deadLetterCount ? 'danger' : 'success'">
            {{ deadLetterCount ? `${deadLetterCount} require attention` : 'Healthy' }}
          </el-tag>
        </div>
      </template>
      <el-table :data="deadLetters" empty-text="No dead-letter jobs">
        <el-table-column prop="id" label="Job" min-width="190">
          <template #default="{ row }">
            <span class="font-mono text-xs">{{ row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="provider_mode" label="Provider" width="110" />
        <el-table-column label="Attempts" width="100">
          <template #default="{ row }">{{ row.attempt_count }} / {{ row.max_attempts }}</template>
        </el-table-column>
        <el-table-column label="Completed" min-width="170">
          <template #default="{ row }">
            {{ row.completed_at ? new Date(row.completed_at).toLocaleString() : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="error" label="Error" min-width="260" show-overflow-tooltip />
        <el-table-column label="Action" width="110" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" plain size="small" @click="requeue(row)">Requeue</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
