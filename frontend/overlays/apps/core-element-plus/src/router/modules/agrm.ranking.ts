import type { RouteRecordRaw } from 'vue-router'

function Layout() {
  return import('@/layouts/index.vue')
}

const routes: RouteRecordRaw = {
  path: '/ranking',
  component: Layout,
  name: 'ranking',
  meta: { title: 'Rank Monitoring', icon: 'i-lucide:chart-no-axes-column-increasing' },
  children: [
    {
      path: 'explorer',
      name: 'rankExplorer',
      component: () => import('@/views/agrm/rank-explorer.vue'),
      meta: { title: 'Rank Explorer', icon: 'i-lucide:search' },
    },
    {
      path: 'monitors',
      name: 'monitors',
      component: () => import('@/views/agrm/monitors.vue'),
      meta: { title: 'Monitors', icon: 'i-lucide:radar' },
    },
    {
      path: 'geo-profiles',
      name: 'geoProfiles',
      component: () => import('@/views/agrm/geo-profiles.vue'),
      meta: { title: 'Geo Profiles', icon: 'i-lucide:map-pin' },
    },
    {
      path: 'history',
      name: 'runHistory',
      component: () => import('@/views/agrm/history.vue'),
      meta: { title: 'Run History', icon: 'i-lucide:history' },
    },
    {
      path: 'competitors',
      name: 'competitiveIntelligence',
      component: () => import('@/views/agrm/competitive-intelligence.vue'),
      meta: { title: 'Competitor Intelligence', icon: 'i-lucide:binoculars' },
    },
    {
      path: 'analytics',
      name: 'analyticsReports',
      component: () => import('@/views/agrm/analytics-reports.vue'),
      meta: { title: 'Analytics & Reports', icon: 'i-lucide:chart-spline' },
    },
  ],
}

export default routes
