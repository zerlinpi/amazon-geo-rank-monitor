<script setup lang="ts">
import { ElMessage } from 'element-plus'

defineOptions({ name: 'McpSetup' })

const stdioConfig = [
  '{',
  '  "mcpServers": {',
  '    "amazon-geo-rank": {',
  '      "command": "agrm-mcp",',
  '      "env": {',
  '        "DATABASE_URL": "postgresql+psycopg://...",',
  '        "MCP_TENANT_ID": "<tenant-id>"',
  '      }',
  '    }',
  '  }',
  '}',
].join('\n')

async function copy() {
  await navigator.clipboard.writeText(stdioConfig)
  ElMessage.success('MCP config copied')
}
</script>

<template>
  <div class="p-4 md:p-6 space-y-5">
    <div>
      <div class="text-xs text-muted-foreground tracking-widest uppercase">Chat integration</div>
      <h1 class="text-2xl font-semibold mt-1">MCP Setup</h1>
      <p class="text-sm text-muted-foreground mt-1">
        The MCP server calls the same rank application services used by REST and the worker.
      </p>
    </div>

    <div class="grid gap-4 xl:grid-cols-2">
      <el-card shadow="never">
        <template #header><span class="font-medium">Local stdio MCP</span></template>
        <p class="text-sm text-muted-foreground mb-4">
          Use a tenant-bound local process for ChatGPT, Claude or another MCP client.
        </p>
        <pre class="p-4 rounded-lg bg-neutral-950 text-neutral-100 text-xs overflow-auto">{{ stdioConfig }}</pre>
        <el-button class="mt-4" @click="copy">Copy config</el-button>
      </el-card>

      <el-card shadow="never">
        <template #header><span class="font-medium">Available tools</span></template>
        <div class="space-y-3">
          <div v-for="tool in [
            'check_rank',
            'create_monitor',
            'run_monitor',
            'get_weighted_rank',
            'get_rank_history',
            'list_geo_profiles',
            'verify_rank',
            'get_credit_balance',
          ]" :key="tool" class="p-3 border rounded-lg font-mono text-sm">
            {{ tool }}
          </div>
        </div>
      </el-card>
    </div>

    <el-alert
      type="info"
      :closable="false"
      title="Security boundary"
      description="MCP does not expose Stripe secrets, provider credentials or raw credit-ledger mutation tools."
    />
  </div>
</template>
