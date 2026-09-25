<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { agrmApi } from '@/api/agrm'

defineOptions({ name: 'ResetPassword' })

const route = useRoute()
const router = useRouter()
const password = ref('')
const confirmation = ref('')
const loading = ref(false)
const completed = ref(false)

async function submit() {
  const token = route.query.token?.toString() || ''
  if (!token) {
    ElMessage.error('Reset token is missing')
    return
  }
  if (password.value.length < 10) {
    ElMessage.warning('Password must be at least 10 characters')
    return
  }
  if (password.value !== confirmation.value) {
    ElMessage.warning('Passwords do not match')
    return
  }
  loading.value = true
  try {
    await agrmApi.resetPassword(token, password.value)
    completed.value = true
    password.value = ''
    confirmation.value = ''
    ElMessage.success('Password reset. All old sessions were signed out.')
  }
  catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Reset link is invalid or expired')
  }
  finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-6">
    <el-card class="w-full max-w-md" shadow="never">
      <template v-if="!completed">
        <div class="text-2xl font-semibold mb-2">Reset password</div>
        <p class="text-sm text-muted-foreground mb-6">
          Choose a new password. Existing browser sessions will be revoked.
        </p>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="New password">
            <el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="At least 10 characters"
            />
          </el-form-item>
          <el-form-item label="Confirm password">
            <el-input
              v-model="confirmation"
              type="password"
              show-password
              autocomplete="new-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button class="w-full" type="primary" :loading="loading" @click="submit">
            Reset password
          </el-button>
        </el-form>
      </template>
      <el-result
        v-else
        icon="success"
        title="Password reset"
        sub-title="You can now sign in with your new password."
      >
        <template #extra>
          <el-button type="primary" @click="router.replace('/login')">Sign in</el-button>
        </template>
      </el-result>
    </el-card>
  </div>
</template>
