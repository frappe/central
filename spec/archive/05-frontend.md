# 05 — Frontend (frappe-ui / espresso)

The Central SPA **mirrors Atlas's frontend** deliberately, so the two apps feel
like one product. Same library, same versions, same composables, same shell
patterns. When in doubt, do what `adityahase/atlas`'s `atlas/frontend` does.

## Stack & layout

- **frappe-ui `^0.1.278`**, **Vue 3**, **vue-router 4**, **Tailwind 3.4**,
  **Vite 5**. Icons via `unplugin-icons` + `lucide`. Build base
  `--base=/assets/central/frontend/`.
- Served at `/dashboard` from `www/dashboard.py` + `dashboard.html` (the
  server-side auth gate from `spec/03`), exactly like Atlas.
- Source layout (mirror Atlas):
  ```
  frontend/src/
    main.js            # FrappeUI plugin + setConfig('resourceFetcher', frappeRequest)
    router.js          # routes nested under AppShell
    App.vue
    AppShell.vue       # Sidebar shell
    pages/             # Assets.vue (registry list), Asset.vue (optional detail)
    components/        # cell renderers, status badge, etc.
    data/              # assets.js (useList), session.js, clusters.js, status.js, format.js
    assets/
  ```

## Design system (espresso)

frappe-ui *is* the espresso design system. **Standard components first** — adopt
the library component even when a hand-rolled one would be shorter (the
maintenance-bar rule, inherited from Atlas):

- Shell: `Sidebar` / `SidebarHeader` / `SidebarSection` / `SidebarItem`.
- Lists: `ListView` (with its built-in `emptyState`).
- Primitives: `Button`, `Badge`, `Breadcrumbs`, `Dropdown`, `FormControl`,
  `Dialog`, imperative `confirmDialog`.
- No bespoke CSS framework, no second component library.

## Routes

Flat, nested under `AppShell`, no client-side auth guard (auth is server-side):

| Path | Page | Notes |
|---|---|---|
| `/` | → redirect `/assets` | |
| `/assets` | `Assets.vue` | **The asset registry list view** (primary v1 screen) |
| `/assets/:name` | `Asset.vue` | *(optional v1)* read-only summary + "Open in Atlas" |

## Data layer

Use frappe-ui composables — **never raw `fetch`** (matches Atlas's `data/`):

```js
// data/assets.js
import { useList } from 'frappe-ui'

export const assets = useList({
  doctype: 'Virtual Machine',
  fields: ['name','title','cluster','team','status_cached','status_synced_at',
           'ipv6_address','vcpus','memory_megabytes','plan_id','last_synced'],
  orderBy: 'modified desc',
  pageLength: 100,
  cacheKey: 'assets',
})
```

`main.js` sets `setConfig('resourceFetcher', frappeRequest)` so every call carries
the session cookie + CSRF and hits `/api`. `session.js` reads `window.user` /
`window.csrf_token` / `window.site_name` injected by the server gate, and logs out
via `window.location.href = '/api/method/logout'`.

## The asset registry list view (`Assets.vue`)

The one screen that matters in v1. A single cross-cluster `ListView` of everything
the user owns.

**Columns** (label → source):
| Column | Source | Cell rendering |
|---|---|---|
| Name | `title` (fallback `vm_id`) | link-style; click ⇒ hand-off (`spec/04`) |
| Cluster / Region | `cluster` | text + small region tag |
| Status | `status_cached` | **Badge** (green Running / gray Stopped / amber Pending / red Failed / muted Unknown). Lazily refreshed via W4 after paint. |
| Address | `ipv6_address` | **copy** cell |
| Size | `vcpus` / `memory_megabytes` | compact "2 vCPU · 4 GB" |
| Last seen | `last_synced` | **relative time** |

> `ListView` has **no built-in cell types** for badge/copy/relative-time/link, so
> (as Atlas does) provide a `#cell` dispatcher slot that renders the right
> component per `column.key`. Keep these renderers in `components/`.

**Controls:**
- **Search** by name.
- **Filters:** Cluster (from `clusters.js`), Status, Team.
- **Per-row action / row click → "Open"** ⇒ `window.location` redirect to the
  cluster deep link (triggers SSO, `spec/03`).
- **Cluster header action → "Open cluster console"** ⇒ redirect to
  `{base_url}/dashboard/machines`.
- **`emptyState`:** "No assets yet" with a hint to create one in a cluster.
- **Stale/degraded affordance:** if a cluster's `last_sync_error` is set, show a
  subtle banner/tag ("Bangalore: last synced 12m ago") rather than failing the
  list — blast-radius rule.

## What the frontend must NOT do

- No synchronous fan-out to clusters on page load (render from registry rows).
- No embedding Atlas in an iframe; no proxying Atlas operations.
- No storing/echoing live metrics beyond the W4 status badge.
