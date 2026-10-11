<script setup lang="ts">
import type { NotificationStatus } from '@/api/agrm'
import { agrmApi } from '@/api/agrm'

const props = withDefaults(defineProps<{ showConfigured?: boolean }>(), {
  showConfigured: false,
})
const status = ref<NotificationStatus | null>(null)
const loading = ref(false)
const failed = ref(false)
const visible = computed(() => failed.value || status.value?.email.configured === false
  || (props.showConfigured && status.value !== null))
const title = computed(() => failed.value
  ? 'Unable to load email configuration'
  : status.value?.email.configured ? 'Email delivery configured' : 'Email delivery is not configured')

async function refresh() {
  loading.value = true
  try {
    status.value = await agrmApi.getNotificationStatus()
    failed.value = false
  }
  catch {
    status.value = null
    failed.value = true
  }
  finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <el-alert
    v-if="visible"
    :title="title"
    :type="status?.email.configured ? 'info' : 'warning'"
    :closable="false"
    show-icon
  >
    <p v-if="failed">
      Email configuration could not be checked. Refresh to try again.
    </p>
    <p v-else-if="status?.email.configured">
      Check delivery history for each send attempt. Configuration does not guarantee delivery.
    </p>
    <p v-else>
      Email alerts and scheduled reports cannot be sent. Ask an administrator to enable email delivery.
    </p>
    <el-button class="mt-2" size="small" :loading="loading" @click="refresh">
      Refresh delivery status
    </el-button>
  </el-alert>
</template>
