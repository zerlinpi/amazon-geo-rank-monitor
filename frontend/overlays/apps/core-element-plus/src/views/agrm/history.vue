<script setup lang="ts">
import { agrmApi, type RankRun } from '@/api/agrm'

defineOptions({ name: 'RunHistory' })

const loading = ref(false)
const rows = ref<RankRun[]>([])
const selected = ref<RankRun | null>(null)
const dialog = ref(false)

async function load() {
  loading.value = true
  try {
    rows.value = await agrmApi.getRuns(100)
  }
  finally {
    loading.value = false
  }
}

function view(row: any) {
  const run = row as RankRun
  selected.value = run
  dialog.value = true
}

function strictStatus(row: RankRun) {
  const meta = row.verification_metadata
  const requested = meta?.strict_requested_count || 0
  if (!meta?.auto_strict_enabled) {
    return { label: 'Off', type: 'info' as const }
  }
  if (!requested) {
    return { label: 'Not triggered', type: 'success' as const }
  }
  if ((meta.strict_succeeded_count || 0) === requested) {
    return { label: `Strict ${requested}/${requested}`, type: 'success' as const }
  }
  if (meta.strict_skipped_count) {
    return { label: `Skipped ${meta.strict_skipped_count}`, type: 'warning' as const }
  }
  return {
    label: `Strict ${meta.strict_succeeded_count || 0}/${requested}`,
    type: 'warning' as const,
  }
}

function triggerLabel(trigger: string) {
  if (trigger.startsWith('low_confidence:')) {
    return `Low confidence ${Math.round(Number(trigger.split(':')[1]) * 100)}%`
  }
  if (trigger.startsWith('rank_movement:')) {
    const [, asin, delta] = trigger.split(':')
    return `Rank moved ${asin} by ${delta}`
  }
  if (trigger.startsWith('not_found_after_found:')) {
    return `Previously found ASIN disappeared: ${trigger.split(':')[1]}`
  }
  const labels: Record<string, string> = {
    managed_probe_failed: 'Managed probe failed',
    geo_country_mismatch: 'IP country mismatch',
    geo_postal_mismatch: 'IP postal mismatch',
    delivery_postal_mismatch: 'Delivery postal mismatch',
  }
  return labels[trigger] || trigger
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">Audit evidence</div>
      <h1 class="text-2xl font-semibold mt-1">Run History</h1>
      <p class="text-sm text-muted-foreground mt-1">Weighted scores remain traceable to every regional observation.</p>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="rows" @row-dblclick="view">
        <el-table-column prop="keyword" label="Keyword" min-width="180" />
        <el-table-column prop="marketplace" label="Marketplace" width="130" />
        <el-table-column label="Status" width="150">
          <template #default="{ row }">
            <el-tag :type="row.status === 'succeeded' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Snapshots" width="100">
          <template #default="{ row }">{{ row.snapshots.length }}</template>
        </el-table-column>
        <el-table-column label="Requested" width="100">
          <template #default="{ row }">{{ row.requested_probe_count }}</template>
        </el-table-column>
        <el-table-column label="Upstream" width="100">
          <template #default="{ row }">{{ row.settled_probe_count }}</template>
        </el-table-column>
        <el-table-column label="Cache" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.cache_hit_count" type="success" size="small">
              {{ row.cache_hit_count }}
            </el-tag>
            <span v-else>0</span>
          </template>
        </el-table-column>
        <el-table-column label="Auto verify" width="140">
          <template #default="{ row }">
            <el-tag :type="strictStatus(row as RankRun).type" size="small">
              {{ strictStatus(row as RankRun).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Started" min-width="170">
          <template #default="{ row }">{{ new Date(row.started_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="Action" width="90">
          <template #default="{ row }"><el-button text @click="view(row)">View</el-button></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" title="Rank run details" width="min(1000px, 96vw)">
      <template v-if="selected">
        <div class="grid gap-3 mb-5 sm:grid-cols-3">
          <div class="p-3 border rounded-lg">
            <div class="text-xs text-muted-foreground">Requested probes</div>
            <div class="text-2xl font-semibold mt-1">{{ selected.requested_probe_count }}</div>
          </div>
          <div class="p-3 border rounded-lg">
            <div class="text-xs text-muted-foreground">Upstream / billable</div>
            <div class="text-2xl font-semibold mt-1">{{ selected.settled_probe_count }}</div>
          </div>
          <div class="p-3 border rounded-lg">
            <div class="text-xs text-muted-foreground">Cache hits</div>
            <div class="text-2xl font-semibold mt-1">{{ selected.cache_hit_count }}</div>
          </div>
        </div>
        <el-card
          v-if="selected.verification_metadata?.auto_strict_enabled"
          shadow="never"
          class="mb-5"
        >
          <template #header>
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="font-medium">Automatic strict verification</div>
                <div class="text-xs text-muted-foreground mt-1">
                  Managed anomalies and low-confidence Geo failures are rechecked with the strict browser provider.
                </div>
              </div>
              <el-tag :type="strictStatus(selected).type">
                {{ strictStatus(selected).label }}
              </el-tag>
            </div>
          </template>
          <div
            v-if="selected.verification_metadata.events?.length"
            class="space-y-3"
          >
            <div
              v-for="event in selected.verification_metadata.events"
              :key="event.geo_profile_id + event.triggers.join(':')"
              class="rounded-lg border p-3"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="font-mono text-xs">{{ event.geo_profile_id }}</div>
                <div class="flex items-center gap-2">
                  <el-tag v-if="event.cache_hit" type="success" size="small">Strict cache</el-tag>
                  <el-tag
                    :type="event.succeeded ? 'success' : event.skipped_reason ? 'warning' : 'danger'"
                    size="small"
                  >
                    {{ event.succeeded ? 'Verified' : event.skipped_reason ? 'Skipped' : 'Failed' }}
                  </el-tag>
                </div>
              </div>
              <div class="flex flex-wrap gap-2 mt-3">
                <el-tag
                  v-for="trigger in event.triggers"
                  :key="trigger"
                  type="info"
                  size="small"
                  effect="plain"
                >
                  {{ triggerLabel(trigger) }}
                </el-tag>
              </div>
              <div v-if="event.skipped_reason" class="text-xs text-muted-foreground mt-2">
                Skip reason: {{ event.skipped_reason }}
              </div>
              <div v-if="event.error" class="text-xs text-red-500 mt-2">
                {{ event.error }}
              </div>
            </div>
          </div>
          <div v-else class="text-sm text-muted-foreground">
            No strict verification was required for this run.
          </div>
        </el-card>
        <div class="grid gap-3 mb-5 sm:grid-cols-2 xl:grid-cols-4">
          <el-card v-for="snapshot in selected.snapshots" :key="snapshot.asin" shadow="never">
            <div class="font-mono text-xs text-muted-foreground">{{ snapshot.asin }}</div>
            <div class="text-3xl font-semibold mt-2">#{{ snapshot.weighted_rank }}</div>
            <div class="text-xs text-muted-foreground mt-2">Confidence {{ Math.round(Number(snapshot.confidence) * 100) }}%</div>
          </el-card>
        </div>
        <el-table :data="selected.observations" max-height="420">
          <el-table-column prop="asin" label="ASIN" min-width="140" />
          <el-table-column prop="geo_profile_id" label="Geo" min-width="180" />
          <el-table-column prop="organic_rank" label="Organic" width="100">
            <template #default="{ row }">{{ row.organic_rank ? '#' + row.organic_rank : 'Not found' }}</template>
          </el-table-column>
          <el-table-column prop="absolute_rank" label="Absolute" width="100" />
          <el-table-column prop="sponsored_rank" label="Sponsored" width="110" />
          <el-table-column prop="provider" label="Provider" width="120" />
          <el-table-column label="Verification" width="130">
            <template #default="{ row }">
              <el-tag
                :type="row.verification_level === 'strict' ? 'success' : 'info'"
                size="small"
              >
                {{ row.verification_level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Source" width="150">
            <template #default="{ row }">
              <el-tag :type="row.probe_source === 'cache' ? 'success' : 'info'" size="small">
                {{ row.probe_source === 'cache'
                  ? 'Cache · ' + (row.cache_age_seconds ?? 0) + 's old'
                  : 'Upstream' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-alert v-if="selected.error_summary" class="mt-4" type="warning" :closable="false" :title="selected.error_summary" />
      </template>
    </el-dialog>
  </div>
</template>
