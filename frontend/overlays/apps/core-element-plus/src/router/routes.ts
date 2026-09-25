import type { RouteRecordMainRaw } from '@fantastic-admin/types'
import type { RouteRecordRaw } from 'vue-router'
import pinia from '@/store'
import Ranking from './modules/agrm.ranking'
import Workspace from './modules/agrm.workspace'

const constantRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login.vue'),
    meta: { title: 'Sign in' },
  },
  {
    path: '/verify-email',
    name: 'verifyEmail',
    component: () => import('@/views/verify-email.vue'),
    meta: { title: 'Verify email' },
  },
  {
    path: '/reset-password',
    name: 'resetPassword',
    component: () => import('@/views/reset-password.vue'),
    meta: { title: 'Reset password' },
  },
  {
    path: '/sso-complete',
    name: 'ssoComplete',
    component: () => import('@/views/sso-complete.vue'),
    meta: { title: 'Completing SSO' },
  },
  {
    path: '/:all(.*)*',
    name: 'notFound',
    component: () => import('@/views/[...all].vue'),
    meta: { title: 'Not found' },
  },
]

const systemRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/index.vue'),
    meta: { breadcrumb: false },
    children: [
      {
        path: '',
        component: () => import('@/views/index.vue'),
        meta: {
          title: useAppSettingsStore(pinia).settings.app.home.title,
          icon: 'i-ant-design:home-twotone',
          breadcrumb: false,
        },
      },
      {
        path: 'reload',
        name: 'reload',
        component: () => import('@/views/reload.vue'),
        meta: { title: 'Reloading...', breadcrumb: false },
      },
    ],
  },
]

const asyncRoutes: RouteRecordMainRaw[] = [
  {
    meta: {
      title: 'Rank Monitoring',
      icon: 'i-lucide:chart-no-axes-column-increasing',
    },
    children: [Ranking],
  },
  {
    meta: {
      title: 'Workspace',
      icon: 'i-lucide:settings-2',
    },
    children: [Workspace],
  },
]

export { asyncRoutes, constantRoutes, systemRoutes }
