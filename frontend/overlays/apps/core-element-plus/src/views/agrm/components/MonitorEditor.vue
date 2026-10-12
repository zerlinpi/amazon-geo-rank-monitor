<script setup lang="ts">
import { agrmApi, type GeoProfile, type Monitor } from '@/api/agrm'
import { apiErrorMessage } from '@/utils/api-error'

const props = defineProps<{ monitor: Monitor | null, geos: GeoProfile[] }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [monitor: Monitor] }>()
const submitting = ref(false)
const error = ref('')
const advanced = ref<string[]>([])
const schedules = [
  { label: 'Manual only', value: 'manual' },
  { label: 'Every hour (UTC)', value: '0 * * * *' },
  { label: 'Every 6 hours (UTC)', value: '0 */6 * * *' },
  { label: 'Daily at 09:00 UTC', value: '0 9 * * *' },
  { label: 'Custom schedule', value: 'custom' },
]
const form = reactive({
  name: '', keyword: '', asinsText: '', geo_profile_ids: [] as string[],
  marketplace: 'amazon.com', search_depth: 100,
  provider_mode: 'managed' as 'managed' | 'strict', frequency: 'manual', schedule: '',
})
const availableGeos = computed(() => props.geos.filter(geo => geo.marketplace === form.marketplace))

watch(open, (value) => {
  if (!value) return
  const row = props.monitor
  Object.assign(form, {
    name: row?.name ?? '', keyword: row?.keyword ?? '', asinsText: row?.asins.join('\n') ?? '',
    geo_profile_ids: [...(row?.geo_profile_ids ?? [])], marketplace: row?.marketplace ?? 'amazon.com',
    search_depth: row?.search_depth ?? 100, provider_mode: row?.provider_mode ?? 'managed',
    frequency: !row?.schedule ? 'manual' : schedules.some(option => option.value === row.schedule) ? row.schedule : 'custom',
    schedule: row?.schedule ?? '',
  })
  advanced.value = row && (row.provider_mode !== 'managed' || row.search_depth !== 100 || row.marketplace !== 'amazon.com') ? ['advanced'] : []
  error.value = ''
})

async function save() {
  if (submitting.value) return
  error.value = ''
  const asins = [...new Set(form.asinsText.split(/[\n,\s]+/).map(item => item.trim().toUpperCase()).filter(Boolean))]
  if (!form.name.trim() || !form.keyword.trim() || !asins.length || !form.geo_profile_ids.length) {
    error.value = 'Name, keyword, ASINs and at least one Geo Profile are required.'
    return
  }
  const schedule = form.frequency === 'manual' ? '' : form.frequency === 'custom' ? form.schedule.trim() : form.frequency
  if (form.frequency === 'custom' && schedule.split(/\s+/).length !== 5) {
    error.value = 'Enter a five-field cron schedule in UTC, or select Manual only.'
    return
  }
  submitting.value = true
  try {
    const payload = {
      name: form.name.trim(), keyword: form.keyword.trim(), asins,
      geo_profile_ids: [...form.geo_profile_ids], marketplace: form.marketplace,
      search_depth: form.search_depth, provider_mode: form.provider_mode, schedule: schedule || null,
    }
    const monitor = props.monitor
      ? await agrmApi.updateMonitor(props.monitor.id, payload)
      : await agrmApi.createMonitor(payload)
    open.value = false
    emit('saved', monitor)
  }
  catch (cause) {
    error.value = apiErrorMessage(cause, 'Unable to save this monitor. Your input has been kept; please try again.')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="open" :title="monitor ? 'Edit monitor' : 'Create monitor'" width="min(680px, 92vw)" :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting">
    <el-form label-position="top" :disabled="submitting" @submit.prevent="save">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb-4" />
      <el-form-item label="Name" for="monitor-name">
        <el-input id="monitor-name" v-model="form.name" placeholder="Trailer hitch · US" />
      </el-form-item>
      <el-form-item label="Keyword" for="monitor-keyword">
        <el-input id="monitor-keyword" v-model="form.keyword" placeholder="trailer hitch" />
      </el-form-item>
      <el-form-item label="ASINs" for="monitor-asins">
        <el-input id="monitor-asins" v-model="form.asinsText" type="textarea" :rows="3" placeholder="One ASIN per line, or separate with commas" />
        <p class="text-xs text-muted-foreground mt-1">Duplicates are removed automatically.</p>
      </el-form-item>
      <el-form-item label="Geo Profiles" for="monitor-geos">
        <el-select id="monitor-geos" v-model="form.geo_profile_ids" multiple class="w-full" placeholder="Select geographies">
          <el-option v-for="geo in availableGeos" :key="geo.id" :label="`${geo.name} · ${geo.delivery_postal_code}`" :value="geo.id" :disabled="!geo.enabled && !form.geo_profile_ids.includes(geo.id)" />
        </el-select>
      </el-form-item>
      <el-form-item label="Run frequency" for="monitor-frequency">
        <el-select id="monitor-frequency" v-model="form.frequency" class="w-full">
          <el-option v-for="option in schedules" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <p class="text-xs text-muted-foreground mt-1">Scheduled times use UTC. Manual only runs when you click Run now.</p>
      </el-form-item>
      <el-form-item v-if="form.frequency === 'custom'" label="Custom UTC cron" for="monitor-schedule">
        <el-input id="monitor-schedule" v-model="form.schedule" placeholder="0 */6 * * *" />
      </el-form-item>
      <el-collapse v-model="advanced">
        <el-collapse-item title="Advanced settings" name="advanced">
          <el-form-item label="Marketplace" for="monitor-marketplace">
            <el-select id="monitor-marketplace" v-model="form.marketplace" class="w-full">
              <el-option label="Amazon.com (US)" value="amazon.com" />
              <el-option v-if="form.marketplace !== 'amazon.com'" :label="form.marketplace" :value="form.marketplace" />
            </el-select>
          </el-form-item>
          <el-form-item label="Search depth" for="monitor-depth">
            <el-input-number id="monitor-depth" v-model="form.search_depth" :min="1" :max="Math.max(500, monitor?.search_depth ?? 500)" />
          </el-form-item>
          <el-form-item label="Provider" for="monitor-provider">
            <el-select id="monitor-provider" v-model="form.provider_mode" class="w-full">
              <el-option label="Managed" value="managed" />
              <el-option label="Strict verify" value="strict" />
            </el-select>
          </el-form-item>
          <p class="text-sm text-muted-foreground">Managed is the default for routine monitoring. Strict requires configured proxy verification and can use more credits. Set automatic verification separately from More → Verification policy.</p>
        </el-collapse-item>
      </el-collapse>
      <p class="text-xs text-muted-foreground mt-4">Saving does not start a manual run. A scheduled monitor becomes eligible when its next UTC time is due.</p>
    </el-form>
    <template #footer>
      <el-button :disabled="submitting" @click="open = false">Cancel</el-button>
      <el-button type="primary" :loading="submitting" @click="save">{{ monitor ? 'Save changes' : 'Create' }}</el-button>
    </template>
  </el-dialog>
</template>
