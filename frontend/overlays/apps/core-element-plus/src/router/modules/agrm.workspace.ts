import type { RouteRecordRaw } from 'vue-router'

function Layout() {
  return import('@/layouts/index.vue')
}

const routes: RouteRecordRaw = {
  path: '/workspace',
  component: Layout,
  name: 'workspace',
  meta: { title: 'Workspace', icon: 'i-lucide:settings-2' },
  children: [
    {
      path: 'billing',
      name: 'billing',
      component: () => import('@/views/agrm/billing.vue'),
      meta: { title: 'Credits & Billing', icon: 'i-lucide:wallet-cards' },
    },
    {
      path: 'api-keys',
      name: 'apiKeys',
      component: () => import('@/views/agrm/api-keys.vue'),
      meta: { title: 'API Keys', icon: 'i-lucide:key-round' },
    },
    {
      path: 'mcp',
      name: 'mcpSetup',
      component: () => import('@/views/agrm/mcp.vue'),
      meta: { title: 'MCP Setup', icon: 'i-lucide:plug-zap' },
    },
  ],
}

export default routes
