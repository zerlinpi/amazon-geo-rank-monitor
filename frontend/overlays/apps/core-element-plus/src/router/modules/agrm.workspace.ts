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
      path: 'security',
      name: 'accountSecurity',
      component: () => import('@/views/agrm/security.vue'),
      meta: { title: 'Account Security', icon: 'i-lucide:shield-check' },
    },
    {
      path: 'team',
      name: 'team',
      component: () => import('@/views/agrm/team.vue'),
      meta: { title: 'Team', icon: 'i-lucide:users' },
    },
    {
      path: 'api-keys',
      name: 'apiKeys',
      component: () => import('@/views/agrm/api-keys.vue'),
      meta: { title: 'API Keys', icon: 'i-lucide:key-round' },
    },
    {
      path: 'alerts',
      name: 'rankAlerts',
      component: () => import('@/views/agrm/alerts.vue'),
      meta: { title: 'Rank Alerts', icon: 'i-lucide:bell-ring' },
    },
    {
      path: 'system-status',
      name: 'systemStatus',
      component: () => import('@/views/agrm/system-status.vue'),
      meta: { title: 'System Status', icon: 'i-lucide:activity' },
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
