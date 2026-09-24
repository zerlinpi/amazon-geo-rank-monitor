<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi, type GeoProfile } from '@/api/agrm'

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
})
const result = ref<any | null>(null)

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
          <el-button type="primary" size="large" :loading="loading" @click="submit">
            Run rank check
          </el-button>
        </div>
      </el-form>
    </el-card>

    <template v-if="result">
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
        </el-table>
      </el-card>
    </template>
  </div>
</template>
