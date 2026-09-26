<script setup lang="ts">
import type {
  AlertEvent,
  AlertRule,
  AlertRulePayload,
  GeoProfile,
  Monitor,
} from '@/api/agrm'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'RankAlerts' })

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const rules = ref<AlertRule[]>([])
const events = ref<AlertEvent[]>([])
const monitors = ref<Monitor[]>([])
const geos = ref<GeoProfile[]>([])
const dialog = ref(false)
const editingId = ref<string | null>(null)

const form = reactive({
  monitor_target_id: '',
  name: '',
  rule_type: 'rank_drop',
  threshold: 10,
  asin: '',
  geo_profile_id: '',
  cooldown_minutes: 60,
  enabled: true,
  emailsText: '',
  slack_webhook_url: '',
  webhook_url: '',
  replaceChannels: true,
})

const ruleTypes = [
  { value: 'rank_drop', label: 'Rank drops by N+' },
  { value: 'rank_improve', label: 'Rank improves by N+' },
  { value: 'enters_top_n', label: 'Enters Top N' },
  { value: 'exits_top_n', label: 'Exits Top N' },
  { value: 'not_found', label: 'Not found anywhere' },
  { value: 'geo_not_found', label: 'Not found in geo' },
  { value: 'geo_rank_above', label: 'Geo rank worse than N' },
  { value: 'competitor_enters_top_n', label: 'Competitor enters Top N' },
  { value: 'competitor_exits_top_n', label: 'Competitor exits Top N' },
  { value: 'competitor_sov_gain', label: 'Competitor SOV gains N+ points' },
  { value: 'competitor_sov_loss', label: 'Competitor SOV loses N+ points' },
  { value: 'competitor_overtakes_tracked', label: 'Competitor overtakes tracked ASINs' },
  { value: 'strict_verification_failed', label: 'Strict verification fails' },
  { value: 'strict_insufficient_credits', label: 'Strict skipped · insufficient credits' },
  { value: 'strict_probe_budget_exhausted', label: 'Strict skipped · probe budget exhausted' },
  { value: 'strict_provider_unavailable', label: 'Strict skipped · provider unavailable' },
  { value: 'strict_runtime_disabled', label: 'Strict blocked · runtime kill switch' },
]

const thresholdRequired = computed(() =>
  [
    'rank_drop',
    'rank_improve',
    'enters_top_n',
    'exits_top_n',
    'geo_rank_above',
    'competitor_enters_top_n',
    'competitor_exits_top_n',
    'competitor_sov_gain',
    'competitor_sov_loss',
  ].includes(form.rule_type),
)
const competitiveRule = computed(() =>
  form.rule_type.startsWith('competitor_'),
)
const verificationRule = computed(() =>
  form.rule_type.startsWith('strict_'),
)
const geoRule = computed(() =>
  ['geo_not_found', 'geo_rank_above'].includes(form.rule_type)
  || verificationRule.value,
)
const selectedMonitor = computed(() =>
  monitors.value.find(item => item.id === form.monitor_target_id),
)
const selectedGeoIds = computed(() =>
  selectedMonitor.value?.geo_profile_ids || [],
)
const selectedAsins = computed(() =>
  selectedMonitor.value?.asins || [],
)

function monitorName(id: string) {
  return monitors.value.find(item => item.id === id)?.name || id
}

function geoName(id?: string | null) {
  if (!id) {
    return 'Aggregate'
  }
  return geos.value.find(item => item.id === id)?.name || id
}

function ruleTypeLabel(type: string) {
  return ruleTypes.find(item => item.value === type)?.label || type
}

function channelText(row: any) {
  const channels = []
  if (row.channels.email_count) {
    channels.push(`Email ×${row.channels.email_count}`)
  }
  if (row.channels.has_slack) {
    channels.push('Slack')
  }
  if (row.channels.has_webhook) {
    channels.push('Webhook')
  }
  return channels.join(' · ') || '—'
}

async function load() {
  loading.value = true
  try {
    const [ruleData, eventData, monitorData, geoData] = await Promise.all([
      agrmApi.getAlertRules(),
      agrmApi.getAlertEvents(100),
      agrmApi.getMonitors(),
      agrmApi.getGeoProfiles(),
    ])
    rules.value = ruleData
    events.value = eventData
    monitors.value = monitorData
    geos.value = geoData
  }
  finally {
    loading.value = false
  }
}

function resetForm() {
  const hintedMonitor = route.query.monitor?.toString() || monitors.value[0]?.id || ''
  const hintedCompetitor = route.query.competitor?.toString().trim().toUpperCase() || ''
  Object.assign(form, {
    monitor_target_id: hintedMonitor,
    name: hintedCompetitor ? hintedCompetitor + ' enters Top 10' : '',
    rule_type: hintedCompetitor ? 'competitor_enters_top_n' : 'rank_drop',
    threshold: 10,
    asin: hintedCompetitor,
    geo_profile_id: '',
    cooldown_minutes: 60,
    enabled: true,
    emailsText: '',
    slack_webhook_url: '',
    webhook_url: '',
    replaceChannels: true,
  })
  editingId.value = null
}

function openCreate() {
  resetForm()
  dialog.value = true
}

function openEdit(row: AlertRule) {
  editingId.value = row.id
  Object.assign(form, {
    monitor_target_id: row.monitor_target_id,
    name: row.name,
    rule_type: row.rule_type,
    threshold: Number(row.threshold || 10),
    asin: row.asin || '',
    geo_profile_id: row.geo_profile_id || '',
    cooldown_minutes: row.cooldown_minutes,
    enabled: row.enabled,
    emailsText: row.channels.emails.join('\n'),
    slack_webhook_url: '',
    webhook_url: '',
    replaceChannels: false,
  })
  dialog.value = true
}

function normalizeEmails() {
  return form.emailsText
    .split(/[\n,;]+/)
    .map(item => item.trim().toLowerCase())
    .filter(Boolean)
}

async function save() {
  if (!form.monitor_target_id || !form.name.trim()) {
    ElMessage.warning('Monitor and rule name are required')
    return
  }
  if (thresholdRequired.value && form.threshold <= 0) {
    ElMessage.warning('Threshold must be greater than zero')
    return
  }
  if (geoRule.value && form.geo_profile_id && !selectedGeoIds.value.includes(form.geo_profile_id)) {
    ElMessage.warning('Selected geo is not part of the monitor')
    return
  }
  if (
    competitiveRule.value
    && !/^[A-Z0-9]{10}$/.test(form.asin.trim().toUpperCase())
  ) {
    ElMessage.warning('Competitor ASIN must be 10 letters/numbers')
    return
  }

  const base = {
    monitor_target_id: form.monitor_target_id,
    name: form.name.trim(),
    rule_type: form.rule_type,
    threshold: thresholdRequired.value ? form.threshold : null,
    asin: verificationRule.value
      ? null
      : (form.asin.trim().toUpperCase() || null),
    geo_profile_id: geoRule.value ? (form.geo_profile_id || null) : null,
    cooldown_minutes: form.cooldown_minutes,
    enabled: form.enabled,
  }

  saving.value = true
  try {
    if (editingId.value) {
      const payload: Partial<AlertRulePayload> = { ...base }
      if (form.replaceChannels) {
        payload.channels = {
          emails: normalizeEmails(),
          slack_webhook_url: form.slack_webhook_url.trim() || null,
          webhook_url: form.webhook_url.trim() || null,
        }
      }
      await agrmApi.updateAlertRule(editingId.value, payload)
      ElMessage.success('Alert rule updated')
    }
    else {
      const payload: AlertRulePayload = {
        ...base,
        channels: {
          emails: normalizeEmails(),
          slack_webhook_url: form.slack_webhook_url.trim() || null,
          webhook_url: form.webhook_url.trim() || null,
        },
      }
      await agrmApi.createAlertRule(payload)
      ElMessage.success('Alert rule created')
    }
    dialog.value = false
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to save alert rule')
  }
  finally {
    saving.value = false
  }
}

async function toggle(row: AlertRule) {
  try {
    await agrmApi.updateAlertRule(row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? 'Alert disabled' : 'Alert enabled')
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to update alert')
  }
}

async function archive(row: AlertRule) {
  try {
    await ElMessageBox.confirm(
      `Archive alert rule "${row.name}"? Alert history will be retained.`,
      'Archive alert',
      { type: 'warning', confirmButtonText: 'Archive' },
    )
    await agrmApi.deleteAlertRule(row.id)
    ElMessage.success('Alert rule archived')
    await load()
  }
  catch (error: any) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error.response?.data?.detail || 'Failed to archive alert')
  }
}

onMounted(async () => {
  await load()
  if (route.query.monitor) {
    openCreate()
  }
})
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Proactive monitoring</div>
        <h1 class="text-2xl font-semibold mt-1">Rank Alerts</h1>
        <p class="text-sm text-muted-foreground mt-1">
          Detect ranking changes and deliver Email, Slack or allowlisted webhooks.
        </p>
      </div>
      <el-button type="primary" @click="openCreate">Create alert</el-button>
    </div>

    <el-card shadow="never" v-loading="loading">
      <template #header><span class="font-medium">Alert rules</span></template>
      <el-table :data="rules" empty-text="No alert rules yet">
        <el-table-column prop="name" label="Rule" min-width="180" />
        <el-table-column label="Monitor" min-width="160">
          <template #default="{ row }">{{ monitorName(row.monitor_target_id) }}</template>
        </el-table-column>
        <el-table-column label="Condition" min-width="170">
          <template #default="{ row }">
            {{ ruleTypeLabel(row.rule_type) }}
            <span v-if="row.threshold != null"> · {{ row.threshold }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Scope" min-width="170">
          <template #default="{ row }">
            <div class="text-xs">
              <div>{{ row.asin || 'All ASINs' }}</div>
              <div class="text-muted-foreground">{{ geoName(row.geo_profile_id) }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Channels" min-width="170">
          <template #default="{ row }">{{ channelText(row) }}</template>
        </el-table-column>
        <el-table-column label="Cooldown" width="110">
          <template #default="{ row }">{{ row.cooldown_minutes }}m</template>
        </el-table-column>
        <el-table-column label="Status" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? 'Enabled' : 'Disabled' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Actions" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row as AlertRule)">Edit</el-button>
            <el-button size="small" @click="toggle(row as AlertRule)">
              {{ row.enabled ? 'Disable' : 'Enable' }}
            </el-button>
            <el-button size="small" type="danger" text @click="archive(row as AlertRule)">
              Archive
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" v-loading="loading">
      <template #header><span class="font-medium">Recent alert events</span></template>
      <el-table :data="events" empty-text="No alerts triggered yet">
        <el-table-column label="Time" min-width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="Monitor" min-width="150">
          <template #default="{ row }">{{ monitorName(row.monitor_target_id) }}</template>
        </el-table-column>
        <el-table-column prop="asin" label="ASIN" min-width="120" />
        <el-table-column label="Event" min-width="150">
          <template #default="{ row }">{{ ruleTypeLabel(row.event_type) }}</template>
        </el-table-column>
        <el-table-column label="Geo" min-width="130">
          <template #default="{ row }">{{ geoName(row.geo_profile_id) }}</template>
        </el-table-column>
        <el-table-column label="Previous → Current" min-width="150">
          <template #default="{ row }">
            {{ row.previous_value ?? '—' }} → {{ row.current_value ?? '—' }}
          </template>
        </el-table-column>
        <el-table-column label="Delivery" min-width="180">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag
                v-for="delivery in row.deliveries"
                :key="delivery.id"
                :type="delivery.status === 'sent' ? 'success' : 'danger'"
                size="small"
              >
                {{ delivery.channel_type }} · {{ delivery.status }}
              </el-tag>
              <span v-if="!row.deliveries.length" class="text-xs text-muted-foreground">No delivery</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialog"
      :title="editingId ? 'Edit alert rule' : 'Create alert rule'"
      width="min(720px, 94vw)"
      destroy-on-close
    >
      <el-form label-position="top">
        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item label="Monitor">
            <el-select v-model="form.monitor_target_id" class="w-full">
              <el-option
                v-for="monitor in monitors"
                :key="monitor.id"
                :label="monitor.name + ' · ' + monitor.keyword"
                :value="monitor.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="Rule name">
            <el-input v-model="form.name" placeholder="Walking Pad rank drop" />
          </el-form-item>
        </div>

        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item label="Condition">
            <el-select v-model="form.rule_type" class="w-full">
              <el-option
                v-for="item in ruleTypes"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item
            v-if="thresholdRequired"
            :label="form.rule_type.includes('sov_') ? 'SOV change (percentage points)' : 'Threshold / N'"
          >
            <el-input-number v-model="form.threshold" :min="1" :max="500" class="w-full" />
          </el-form-item>
        </div>

        <div class="grid md:grid-cols-2 gap-x-4">
          <el-form-item
            v-if="!verificationRule"
            :label="competitiveRule ? 'Competitor ASIN' : 'ASIN scope'"
          >
            <el-input
              v-if="competitiveRule"
              :model-value="form.asin"
              maxlength="10"
              placeholder="B0XXXXXXXX"
              @input="(value: string) => form.asin = value.toUpperCase()"
            />
            <el-select
              v-else
              v-model="form.asin"
              clearable
              class="w-full"
              placeholder="All tracked ASINs"
            >
              <el-option v-for="asin in selectedAsins" :key="asin" :label="asin" :value="asin" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="geoRule" label="Geo scope">
            <el-select v-model="form.geo_profile_id" clearable class="w-full" placeholder="All monitor geos">
              <el-option
                v-for="geoId in selectedGeoIds"
                :key="geoId"
                :label="geoName(geoId)"
                :value="geoId"
              />
            </el-select>
          </el-form-item>
        </div>

        <el-alert
          v-if="verificationRule"
          class="mb-4"
          type="info"
          :closable="false"
          title="Strict verification alerts are probe-level"
          description="They fire once per matching Geo verification event, not once per tracked ASIN. You can leave Geo empty to watch every Geo in the Monitor."
        />

        <el-form-item label="Cooldown minutes">
          <el-input-number v-model="form.cooldown_minutes" :min="0" :max="10080" />
          <div class="text-xs text-muted-foreground ml-3">
            Suppresses repeated events for the same rule, ASIN and geo.
          </div>
        </el-form-item>

        <el-divider content-position="left">Notification channels</el-divider>

        <el-alert
          v-if="editingId && !form.replaceChannels"
          type="info"
          :closable="false"
          class="mb-4"
          title="Existing webhook URLs are hidden"
          description="Leave channels unchanged, or explicitly choose Replace channels to submit new destinations."
        />

        <el-checkbox v-if="editingId" v-model="form.replaceChannels" class="mb-4">
          Replace notification channels
        </el-checkbox>

        <template v-if="!editingId || form.replaceChannels">
          <el-form-item label="Email recipients">
            <el-input
              v-model="form.emailsText"
              type="textarea"
              :rows="3"
              placeholder="alerts@example.com&#10;ops@example.com"
            />
          </el-form-item>
          <el-form-item label="Slack Incoming Webhook">
            <el-input
              v-model="form.slack_webhook_url"
              type="password"
              show-password
              placeholder="https://hooks.slack.com/services/..."
            />
          </el-form-item>
          <el-form-item label="Generic webhook">
            <el-input
              v-model="form.webhook_url"
              type="password"
              show-password
              placeholder="https://alerts.example.com/hooks/..."
            />
            <div class="text-xs text-muted-foreground mt-1">
              Generic hosts must be explicitly listed in ALERT_WEBHOOK_ALLOWED_HOSTS.
            </div>
          </el-form-item>
        </template>

        <el-checkbox v-model="form.enabled">Enable rule</el-checkbox>
      </el-form>

      <template #footer>
        <el-button @click="dialog = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ editingId ? 'Save changes' : 'Create alert' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
