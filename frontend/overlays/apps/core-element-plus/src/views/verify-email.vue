<script setup lang="ts">
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'VerifyEmail' })

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const success = ref(false)
const message = ref('Verifying your email address…')

onMounted(async () => {
  const token = route.query.token?.toString() || ''
  if (!token) {
    loading.value = false
    message.value = 'Verification token is missing.'
    return
  }
  try {
    await agrmApi.verifyEmail(token)
    success.value = true
    message.value = 'Your email address has been verified.'
  }
  catch (error: any) {
    message.value = error.response?.data?.detail || 'This verification link is invalid or expired.'
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-6">
    <el-card class="w-full max-w-md" shadow="never">
      <div class="text-center space-y-4">
        <div class="text-2xl font-semibold">Email verification</div>
        <el-icon v-if="loading" class="is-loading text-3xl"><Loading /></el-icon>
        <el-result
          v-else
          :icon="success ? 'success' : 'error'"
          :title="success ? 'Verified' : 'Unable to verify'"
          :sub-title="message"
        />
        <el-button type="primary" @click="router.replace('/login')">
          Continue to sign in
        </el-button>
      </div>
    </el-card>
  </div>
</template>
