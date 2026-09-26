<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi, type GeoProfile, type RankCheckResult } from '@/api/agrm'

defineOptions({ name: 'RankExplorer' })

const loading = ref(false)
const geos = ref<GeoProfile[]>([])
const form = reactive({
  marketplace: 'amazon.com',
  keyword: '',
  asinsText: '',
  geo_profile_ids: [] as string[],
  search_depth: 100,
  provider_mode: 'managed' as 'managed' | 'strict',
  force_strict_verification: false,
})
const result = ref<RankCheckResult | null>(null)

async function loadGeos() {
  geos.value = await agrmApi.getGeoProfiles()
}

async function submit() {
  const asins = form.asinsText
    .split(/[\n,\s]+/)
    .map(item => item.trim().toUpperCase())
    .filter(Boolean)
  if (!form.keyword.trim() || !asins.length || !form.geo_profile_ids.length) {
    ElMessage.warning('Keyword, ASIN and at least one Geo Profile are required')
    return
  }
  loading.value = true
  try {
    result.value = await agrmApi.checkRank({
      marketplace: form.marketplace,
      keyword: form.keyword.trim(),
      asins,
      geo_profile_ids: form.geo_profile_ids,
      search_depth: form.search_depth,
      provider_mode: form.provider_mode,
      force_strict_verification: (
        form.provider_mode === 'managed'
        && form.force_strict_verification
      ),
    })
    ElMessage.success('Rank check completed')
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Rank check failed')
  }
  finally {
    loading.value = false
  }
}

onMounted(loadGeos)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">
        On-demand measurement
      </div>
      <h1 class="text-2xl font-semibold mt-1">
        Rank Explorer
      </h1>
      <p class="text-sm text-muted-foreground mt-1">
        One SERP probe per selected geography can match every ASIN in the request.
      </p>
    </div>

    <el-card shadow="never">
      <el-form label-position="top" :model="form">
        <div class="grid gap-x-5 md:grid-cols-2">
          <el-form-item label="Marketplace">
            <el-select v-model="form.marketplace" class="w-full">
              <el-option label="Amazon.com (US)" value="amazon.com" />
            </el-select>
          </el-form-item>
          <el-form-item label="Provider mode">
            <el-radio-group v-model="form.provider_mode">
              <el-radio-button value="managed">
                Managed
              </el-radio-button>
              <el-radio-button value="strict">
                Strict verify
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
        </div>

        <el-form-item label="Keyword">
          <el-input v-model="form.keyword" placeholder="walking pad" />
        </el-form-item>

        <el-form-item label="ASINs">
          <el-input
            v-model="form.asinsText"
            type="textarea"
            :rows="4"
            placeholder="One ASIN per line, or separate with commas"
          />
        </el-form-item>

        <el-form-item label="Geographic profiles">
          <el-checkbox-group v-model="form.geo_profile_ids" class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <el-checkbox v-for="geo in geos" :key="geo.id" :value="geo.id" border>
              {{ geo.name }} · {{ geo.delivery_postal_code }} · weight {{ geo.weight }}
            </el-checkbox>
          </el-checkbox-group>
          <el-empty v-if="!geos.length" description="Create Geo Profiles first" :image-size="70" />
        </el-form-item>

        <div class="flex flex-wrap gap-4 items-end">
          <el-form-item label="Search depth" class="mb-0">
            <el-input-number v-model="form.search_depth" :min="1" :max="500" />
          </el-form-item>
          <el-form-item
            v-if="form.provider_mode === 'managed'"
            label="Manual verification"
            class="mb-0"
          >
            <el-switch
              v-model="form.force_strict_verification"
              active-text="Force strict"
            />
          </el-form-item>
          <el-button type="primary" size="large" :loading="loading" @click="submit">
            Run rank check
          </el-button>
        </div>
        <el-alert
          v-if="form.provider_mode === 'managed' && form.force_strict_verification"
          class="mt-4"
          type="warning"
          :closable="false"
          title="This run will request strict browser verification for each managed Geo."
          description="Strict verification remains subject to the runtime kill switch, available credits, strict cache, and the configured probe budget."
        />
      </el-form>
    </el-card>

    <template v-if="result">
      <el-card shadow="never">
        <template #header>
          <span class="font-medium">Probe usage</span>
        </template>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="p-4 border rounded-lg">
            <div class="text-xs text-muted-foreground">Requested</div>
            <div class="text-3xl font-semibold mt-1">{{ result.usage.requested_probe_count }}</div>
          </div>
          <div class="p-4 border rounded-lg">
            <div class="text-xs text-muted-foreground">Upstream</div>
            <div class="text-3xl font-semibold mt-1">{{ result.usage.upstream_probe_count }}</div>
          </div>
          <div class="p-4 border rounded-lg">
            <div class="text-xs text-muted-foreground">Cache hits</div>
            <div class="text-3xl font-semibold mt-1">{{ result.usage.cache_hit_count }}</div>
          </div>
          <div class="p-4 border rounded-lg">
            <div class="text-xs text-muted-foreground">Billable probes</div>
            <div class="text-3xl font-semibold mt-1">{{ result.usage.billable_probe_count }}</div>
          </div>
        </div>
        <el-alert
          v-if="result.usage.cache_hit_count"
          class="mt-4"
          type="success"
          :closable="false"
          title="Fresh compatible SERP probes were reused and were not billed as new upstream probes."
        />
        <el-alert
          v-if="result.verification?.manual_force_requested"
          class="mt-4"
          type="info"
          :closable="false"
          title="Manual strict verification was requested for this managed run."
        />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span class="font-medium">Weighted organic rank</span>
        </template>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="snapshot in result.snapshots"
            :key="snapshot.asin"
            class="p-4 border rounded-lg"
          >
            <div class="font-mono text-sm text-muted-foreground">
              {{ snapshot.asin }}
            </div>
            <div class="text-4xl font-semibold mt-2">
              #{{ snapshot.weighted_rank }}
            </div>
            <div class="text-xs text-muted-foreground mt-2">
              Confidence {{ Math.round(Number(snapshot.confidence) * 100) }}%
            </div>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span class="font-medium">Regional observations</span>
        </template>
        <el-table :data="result.observations">
          <el-table-column prop="asin" label="ASIN" min-width="140" />
          <el-table-column prop="geo_profile_id" label="Geo Profile" min-width="190" />
          <el-table-column prop="organic_rank" label="Organic" width="110">
            <template #default="{ row }">
              {{ row.organic_rank ? '#' + row.organic_rank : 'Not found' }}
            </template>
          </el-table-column>
          <el-table-column prop="absolute_rank" label="Absolute" width="100" />
          <el-table-column prop="sponsored_rank" label="Sponsored" width="110" />
          <el-table-column prop="provider" label="Provider" width="130" />
          <el-table-column prop="verification_level" label="Verification" width="130" />
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
      </el-card>
    </template>
  </div>
</template>
