<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'Billing' })

const loading = ref(false)
const credits = ref({ balance: 0, reserved: 0, available: 0 })
const packs = ref<any[]>([])
const ledger = ref<any[]>([])

async function load() {
  loading.value = true
  try {
    const [creditData, packData, ledgerData] = await Promise.all([
      agrmApi.getCredits(),
      agrmApi.getCreditPacks(),
      agrmApi.getLedger(100),
    ])
    credits.value = creditData as any
    packs.value = packData as any[]
    ledger.value = ledgerData as any[]
  }
  finally {
    loading.value = false
  }
}

async function buy(pack: any) {
  try {
    const checkout: any = await agrmApi.createCheckout(pack.id)
    location.href = checkout.checkout_url
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Checkout could not be created')
  }
}

function money(pack: any) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: String(pack.currency || 'usd').toUpperCase(),
  }).format(Number(pack.amount_minor) / 100)
}

onMounted(load)
</script>

<template>
  <div class="p-4 md:p-6 space-y-5" v-loading="loading">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">Prepaid usage</div>
      <h1 class="text-2xl font-semibold mt-1">Credits & Billing</h1>
      <p class="text-sm text-muted-foreground mt-1">
        Credits are consumed by actual SERP probes, not by the number of ASINs matched in one SERP.
      </p>
    </div>

    <div class="grid gap-4 sm:grid-cols-3">
      <el-card shadow="never"><el-statistic title="Balance" :value="credits.balance" /></el-card>
      <el-card shadow="never"><el-statistic title="Reserved" :value="credits.reserved" /></el-card>
      <el-card shadow="never"><el-statistic title="Available" :value="credits.available" /></el-card>
    </div>

    <el-card shadow="never">
      <template #header><span class="font-medium">Recharge credits</span></template>
      <div v-if="packs.length" class="grid gap-4 md:grid-cols-3">
        <div v-for="pack in packs" :key="pack.id" class="p-5 border rounded-xl">
          <div class="text-sm text-muted-foreground">{{ pack.name }}</div>
          <div class="text-3xl font-semibold mt-2">{{ pack.credits }}</div>
          <div class="text-sm text-muted-foreground mt-1">credits</div>
          <div class="text-lg font-medium mt-5">{{ money(pack) }}</div>
          <el-button class="w-full mt-4" type="primary" @click="buy(pack)">Recharge</el-button>
        </div>
      </div>
      <el-empty
        v-else
        description="No purchasable credit packs are configured. Set server-side pack prices first."
      />
    </el-card>

    <el-card shadow="never">
      <template #header><span class="font-medium">Credit ledger</span></template>
      <el-table :data="ledger" empty-text="No credit transactions yet">
        <el-table-column prop="entry_type" label="Type" min-width="150" />
        <el-table-column prop="delta_credits" label="Change" width="110">
          <template #default="{ row }">
            <span :class="row.delta_credits > 0 ? 'text-green-600' : row.delta_credits < 0 ? 'text-red-600' : ''">
              {{ row.delta_credits > 0 ? '+' : '' }}{{ row.delta_credits }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="balance_after" label="Balance after" width="130" />
        <el-table-column prop="reference_type" label="Reference" min-width="150" />
        <el-table-column prop="reference_id" label="Reference ID" min-width="220" show-overflow-tooltip />
        <el-table-column label="Time" min-width="180">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
