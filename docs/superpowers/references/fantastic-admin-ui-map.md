# Fantastic Admin UI Reference Map

Pinned upstream: `fantastic-admin/basic@4cf1d0f92c3c7a8651bc41c6c3b65aabbde30af1` (v6.4.0).

| Amazon Geo Rank Monitor UI | Fantastic Admin reference |
| --- | --- |
| Login | `apps/core-element-plus/src/views/login.vue` |
| Global shell | `apps/core-element-plus/src/layouts/index.vue` |
| Router organization | `apps/core-element-plus/src/router/routes.ts` |
| Layout CSS variables | `apps/core-element-plus/src/assets/styles/globals.css` |
| Dashboard cards | `apps/core-element-plus/src/views/index.vue` |
| Tables/forms/dialogs | Element Plus UI examples under core/example apps |
| Theme/light-dark behavior | core Element Plus toolbar/settings patterns |

Rules:

1. Check the pinned upstream implementation before introducing a new page-level UI pattern.
2. Prefer Element Plus controls and upstream spacing/card/navigation conventions.
3. Product-specific ranking, geo, credits, and MCP presentation may add components, but must not introduce another design system.
4. Any directly copied or substantially adapted upstream source keeps the MIT attribution in `THIRD_PARTY_NOTICES.md`.
