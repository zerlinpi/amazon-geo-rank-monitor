<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi, type GeoProfile } from '@/api/agrm'

defineOptions({ name: 'GeoProfiles' })

const rows = ref<GeoProfile[]>([])
const loading = ref(false)
const dialog = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  marketplace: 'amazon.com',
  ip_country: 'US',
  ip_state: '',
  ip_city: '',
  ip_postal_code: '',
  delivery_country: 'US',
  delivery_postal_code: '',
  device: 'desktop' as 'desktop' | 'mobile',
  weight: 10,
  enabled: true,
})

async function load() {
  loading.value = true
  try {
    rows.value = await agrmApi.getGeoProfiles()
  }
  finally {
    loading.value = false
  }
}

async function create() {
  if (!form.name.trim() || !form.delivery_postal_code.trim() || form.weight <= 0) {
    ElMessage.warning('Name, delivery ZIP and positive weight are required')
    return
  }
  submitting.value = true
  try {
    await agrmApi.createGeoProfile({
      name: form.name.trim(),
      marketplace: form.marketplace,
      ip_country: form.ip_country,
      ip_state: form.ip_state.trim() || null,
      ip_city: form.ip_city.trim() || null,
      ip_postal_code: form.ip_postal_code.trim() || null,
      delivery_country: form.delivery_country,
      delivery_postal_code: form.delivery_postal_code.trim(),
      device: form.device,
      weight: form.weight,
      enabled: form.enabled,
    })
    ElMessage.success('Geo Profile created')
    dialog.value = false
    await load()
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to create Geo Profile')
  }
  finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div class="flex flex-wrap gap-3 items-end justify-between">
      <div>
        <div class="text-xs text-muted-foreground tracking-widest uppercase">Observation geography</div>
        <h1 class="text-2xl font-semibold mt-1">Geo Profiles</h1>
        <p class="text-sm text-muted-foreground mt-1">
          IP geography and Amazon Deliver-to address are intentionally stored separately.
        </p>
      </div>
      <el-button type="primary" @click="dialog = true">Add Geo Profile</el-button>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="rows">
        <el-table-column prop="name" label="Name" min-width="150" />
        <el-table-column label="Requested IP" min-width="220">
          <template #default="{ row }">
            {{ [row.ip_city, row.ip_state, row.ip_postal_code].filter(Boolean).join(', ') || row.ip_country }}
          </template>
        </el-table-column>
        <el-table-column label="Deliver-to" min-width="160">
          <template #default="{ row }">{{ row.delivery_country }} {{ row.delivery_postal_code }}</template>
        </el-table-column>
        <el-table-column prop="device" label="Device" width="100" />
        <el-table-column prop="weight" label="Weight" width="100" />
        <el-table-column label="Status" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? 'Enabled' : 'Disabled' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" title="Add Geo Profile" width="min(720px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="Name">
          <el-input v-model="form.name" placeholder="New York · 10001" />
        </el-form-item>
        <div class="grid gap-x-4 md:grid-cols-3">
          <el-form-item label="IP country">
            <el-input v-model="form.ip_country" />
          </el-form-item>
          <el-form-item label="IP state">
            <el-input v-model="form.ip_state" placeholder="NY" />
          </el-form-item>
          <el-form-item label="IP city">
            <el-input v-model="form.ip_city" placeholder="New York" />
          </el-form-item>
        </div>
        <el-form-item label="IP postal code">
          <el-input v-model="form.ip_postal_code" placeholder="10001" />
        </el-form-item>
        <el-divider content-position="left">Amazon Deliver-to</el-divider>
        <div class="grid gap-x-4 md:grid-cols-2">
          <el-form-item label="Delivery country">
            <el-input v-model="form.delivery_country" />
          </el-form-item>
          <el-form-item label="Delivery postal code">
            <el-input v-model="form.delivery_postal_code" placeholder="10001" />
          </el-form-item>
        </div>
        <div class="grid gap-x-4 md:grid-cols-2">
          <el-form-item label="Device">
            <el-select v-model="form.device" class="w-full">
              <el-option label="Desktop" value="desktop" />
              <el-option label="Mobile" value="mobile" />
            </el-select>
          </el-form-item>
          <el-form-item label="Weight">
            <el-input-number v-model="form.weight" :min="0.01" :step="1" />
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
