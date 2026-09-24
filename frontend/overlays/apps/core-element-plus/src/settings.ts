import { setSettings } from '@fantastic-admin/settings'

export default setSettings({
  app: {
    account: {
      auth: true,
    },
    routeMode: 'hash',
    routeBaseOn: 'frontend',
    dynamicTitle: true,
    home: {
      enable: true,
      title: 'Dashboard',
      fullPath: '/',
    },
    copyright: {
      enable: true,
      dates: '2026',
      company: 'Amazon Geo Rank Monitor',
      website: '',
    },
  },
  menu: {
    mode: 'side',
    mainMenuClickMode: 'smart',
    subMenuUniqueExpand: true,
  },
  topbar: {
    tabbar: false,
    toolbar: true,
    mode: 'sticky',
  },
  toolbar: {
    breadcrumb: true,
    menuSearch: {
      enable: true,
      hotkeys: true,
    },
    colorScheme: true,
    fullscreen: true,
    pageReload: true,
  },
})
