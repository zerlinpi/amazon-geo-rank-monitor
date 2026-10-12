<script setup lang="ts">
import { agrmApi, type Monitor, type RankJob, type RankRun } from '@/api/agrm'

const props = defineProps<{ monitor: Monitor | null, queuedJob: RankJob | null }>()
const open = defineModel<boolean>({ required: true })
const router = useRouter()
const entries = ref<{ job: RankJob, run: RankRun | null }[]>([])
const loading = ref(false)
const error = ref('')
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined
const active = (job: RankJob) => ['pending', 'running'].includes(job.status)

function stop() {
  if (timer) clearTimeout(timer)
  timer = undefined
}

function schedule() {
  stop()
  if (open.value && !document.hidden && entries.value.some(entry => active(entry.job))) {
    timer = setTimeout(poll, 3000)
  }
}

async function load() {
  stop()
  const id = props.monitor?.id
  if (!open.value || !id) return
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const rows = await agrmApi.getMonitorHistory(id)
    if (request !== generation || !open.value) return
    entries.value = rows
    // Preserve the just-queued job if a replica has not exposed it in history yet.
    if (props.queuedJob?.monitor_target_id === id && !rows.some(row => row.job.id === props.queuedJob?.id)) {
      entries.value.unshift({ job: props.queuedJob, run: null })
    }
    schedule()
  }
  catch {
    if (request === generation) error.value = 'Unable to refresh monitor activity. Your job has not been resubmitted.'
  }
  finally {
    if (request === generation) loading.value = false
  }
}

async function poll() {
  if (!open.value || document.hidden) return
  const request = generation
  const pending = entries.value.filter(entry => active(entry.job))
  try {
    const jobs = await Promise.all(pending.map(entry => agrmApi.getJob(entry.job.id)))
    if (request !== generation || !open.value || document.hidden) return
    for (const job of jobs) {
      const entry = entries.value.find(row => row.job.id === job.id)
      if (entry) entry.job = job
    }
    if (jobs.some(job => !active(job))) await load()
    else schedule()
  }
  catch {
    if (request === generation) error.value = 'Unable to refresh monitor activity. Your job has not been resubmitted.'
  }
}

function state(job: RankJob) {
  const labels: Record<string, string> = {
    pending: job.attempt_count ? 'Waiting to retry' : 'Queued', running: 'Running',
    succeeded: 'Completed', partially_succeeded: 'Partially completed',
    failed: 'Failed', dead_letter: 'Needs attention', cancelled: 'Cancelled',
  }
  return labels[job.status] ?? job.status
}

function result(job: RankJob) {
  if (!job.run_id) return
  open.value = false
  void router.push({ path: '/ranking/history', query: { run: job.run_id } })
}

function visibilityChanged() {
  if (document.hidden) stop()
  else if (open.value && !loading.value && !error.value) void load()
}

watch(() => [open.value, props.monitor?.id, props.queuedJob?.id], () => {
  ++generation
  stop()
  entries.value = []
  error.value = ''
  loading.value = false
  if (open.value) void load()
})
onMounted(() => document.addEventListener('visibilitychange', visibilityChanged))
onBeforeUnmount(() => {
  ++generation
  stop()
  document.removeEventListener('visibilitychange', visibilityChanged)
})
</script>

<template>
  <el-dialog v-model="open" title="Monitor activity" width="min(760px, 94vw)">
    <p class="font-medium break-words mb-1">{{ monitor?.name }}</p>
    <p class="text-sm text-muted-foreground mb-4">The 10 most recent jobs. Active jobs update automatically while this window is visible.</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb-4" />
    <div v-loading="loading" class="min-h-20 space-y-3" aria-live="polite">
      <el-empty v-if="!loading && !error && !entries.length" description="No jobs yet. Close this window and choose Run now to collect your first result." />
      <div v-for="entry in entries" :key="entry.job.id" class="border rounded p-4 space-y-2">
        <div class="flex flex-wrap gap-2 items-center justify-between">
          <el-tag :type="entry.job.status === 'succeeded' ? 'success' : ['failed', 'dead_letter'].includes(entry.job.status) ? 'danger' : 'warning'">{{ state(entry.job) }}</el-tag>
          <span class="text-xs text-muted-foreground">{{ new Date(entry.job.created_at).toLocaleString() }}</span>
        </div>
        <p v-if="entry.job.status === 'pending'" class="text-sm text-muted-foreground">
          {{ entry.job.attempt_count ? 'Automatic retry is scheduled for ' + new Date(entry.job.available_at).toLocaleString() : 'Waiting for a worker. You can close this window and return through Results.' }}
        </p>
        <p v-if="entry.job.status === 'dead_letter'" class="text-sm">Automatic retries are exhausted. Ask an administrator to check System Status before retrying.</p>
        <p v-if="entry.job.error" class="text-sm break-words">{{ entry.job.error }}</p>
        <p v-if="entry.run?.error_summary" class="text-sm break-words">{{ entry.run.error_summary }}</p>
        <div class="flex flex-wrap gap-3 items-center justify-between">
          <span class="text-xs text-muted-foreground">Attempt {{ entry.job.attempt_count }} / {{ entry.job.max_attempts }}</span>
          <el-button v-if="entry.job.run_id" type="primary" plain size="small" @click="result(entry.job)">View result</el-button>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="open = false">Close</el-button>
      <el-button :loading="loading" @click="load">Refresh activity</el-button>
    </template>
  </el-dialog>
</template>
