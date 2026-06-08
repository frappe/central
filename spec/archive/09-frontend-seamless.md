# 09 — Seamless Frontend

`spec/05` defined Central's SPA. This spec defines how **Central and Atlas (and
later Bench) feel like one product** while staying separately-deployed apps on
separate domains. It is the contract for the shared UI layer, the new frappe-ui
composables, and the mechanics that make a cross-domain hand-off invisible.

## First principles

1. **Separate where failure must be separate; shared where the *look and the
   auth contract* must be identical.** Each plane ships its own SPA on its own
   domain (independent deploys, independent failure domains — `spec/01`). They
   are unified by a **shared package**, not by merging the apps. A single SPA
   that called both planes' APIs would put Central in every region's critical
   path (CORS, coupling, blast-radius violation) — rejected. Micro-frontends /
   module federation — rejected as over-engineering for a 2–3 app system.

2. **The seam is a full-page redirect; the job is to make it imperceptible.**
   You *cannot* avoid a cross-domain navigation (that navigation **is** the SSO,
   `spec/03`). You *can* make it look like an in-app route change: render the
   **identical shell** on both sides, keep assets warm, and bridge with a
   branded transition instead of a white flash.

3. **One design system, one data-fetching convention, one session client —
   versioned and imported, never copy-pasted.** Today Central and Atlas each have
   their own `ResourceList`, `StatusBadge`, `session.js`. That duplication *is*
   the seam. Extract it into `frappe-cloud-ui`.

4. **Standard frappe-ui components first** (the maintenance-bar rule, inherited
   from Atlas). The shared package *wraps and themes* frappe-ui; it does not
   re-implement it.

## Stack baseline (pin it)

- **frappe-ui `v1.0.0-beta.x`** (the v1 line), Vue 3, vue-router 4, Tailwind +
  the **espresso design tokens** (`frappe-ui/tailwind` preset; the v1 line ships
  espresso tokens as first-class), Vite 5.
- **The v1 data-fetching composables** — this is the upgrade from `spec/05`'s
  `^0.1.278`. v1 ships a coherent set with shared client-side stores:

  | Composable | Replaces | Notes |
  |---|---|---|
  | `useList` | `useList` (0.x) | list resource; backed by a shared **`listStore`** |
  | `useDoc` | `useDoc` (0.x) | single document; backed by **`docStore`** (one cached doc instance app-wide) |
  | `useDoctype` | `useDoctype` | doctype-level meta + mutations (`runDocMethod`, delete) |
  | `useCall` | bespoke `frappeRequest` calls | any whitelisted method, with loading/error/refetch state |
  | `useNewDoc` | hand-built insert payloads | local draft → insert |
  | `useFrappeFetch` | raw fetch | the low-level fetcher; wraps CSRF/session/`/api` |
  | `docStore` / `listStore` / `idbStore` | — | shared in-memory caches + **IndexedDB** persistence (instant cold paint, offline-tolerant) |

  Why it matters for *seamless*: `idbStore` lets a returning user see their last
  list **instantly** (from IndexedDB) while the network refetch happens behind
  it — so even a fresh page load after a hand-off paints immediately.

## The shared package — `frappe-cloud-ui`

A standalone **Vue component library, its own repo** (not a Frappe app — no
Python, no doctypes) that both SPAs depend on, exactly like they already both
depend on `frappe-ui`. It owns everything that must look and behave identically.

```
frappe-cloud-ui/                  # its own git repo
  src/
    shell/
      AppShell.vue                # the sidebar + topbar frame, identical on every plane
      PlaneBreadcrumb.vue         # "Frappe Cloud ▸ Bangalore ▸ vm-9" + back-to-Central anchor
      PageHeader.vue
    cells/                        # the ListView #cell dispatcher + renderers
      ResourceList.vue
      StatusBadge.vue  CopyText.vue  RelativeTime.vue  RegionTag.vue
    session/
      useSession.ts               # window boot (user, csrf, site) + logout; one impl
      openInRegion.ts             # the cross-plane hand-off helper (below)
    theme/
      tailwind-preset.js          # re-exports frappe-ui/tailwind + FC brand tokens
      tokens.css
    data/
      conventions.ts              # thin wrappers: standard fields, cacheKey rules
  package.json                    # peerDeps: vue, vue-router, frappe-ui  (NOT deps)
  tailwind-preset.js
```

**`peerDependencies` is the one must-get-right:** `vue`, `vue-router`, and
`frappe-ui` are peers, so the package uses *each host app's* copy. Two copies of
Vue in one bundle silently breaks reactivity and `provide/inject` (the
FrappeUIProvider stops working). Peers prevent it.

**Consumption — three identical touch points in each app** (`apps/central/.../frontend`
and `apps/atlas/.../frontend`), no monorepo, no shared build:

1. **`package.json`** — add it as a dependency, like `frappe-ui`:
   - *dev:* `yarn link frappe-cloud-ui` (or `"file:../../../frappe-cloud-ui"`) so
     edits hot-reload while you work on both at once;
   - *build/deploy:* a **pinned git ref** — `"frappe-cloud-ui": "git+https://…/frappe-cloud-ui#v0.2.0"`.
     Reproducible, **no npm registry needed.** (Same folder `node_modules/frappe-cloud-ui`,
     two possible sources: a symlink to your local checkout in dev, a frozen git
     clone in build.)
2. **`tailwind.config.js`** — use its preset and scan its files:
   ```js
   import fcPreset from 'frappe-cloud-ui/tailwind-preset'
   export default { presets: [fcPreset],
     content: ['./src/**/*.{vue,js}', './node_modules/frappe-cloud-ui/**/*.{vue,js}'] }
   ```
3. **`AppShell.vue`** — a thin wrapper passing plane-specific nav into the shared shell:
   ```vue
   <FCAppShell :plane="'atlas'" :region="'Bangalore'" :sections="atlasNav" :session="session" />
   ```

**Build flow after a shared change:** edit `frappe-cloud-ui` → commit + tag
`v0.3.0` → bump the ref in each app → `yarn install && yarn build` in each app
(this is already each app's frontend build step). **There is no central build —
each app rebuilds itself, independently, pulling the pinned dependency.** Pin
**tags/SHAs** (deliberate bump) over a tracked branch, so a build's output is
reproducible once Central and Atlas deploy independently.

> Publishing `frappe-cloud-ui` to a (private) npm registry with full semver is a
> *later* convenience, only once these apps leave the bench — **not** built now.
> The **shell, theme, cells, and session client have one source of truth** either
> way.

> What stays app-local: the *pages* (`Assets.vue` in Central; `Machines.vue`,
> `Machine.vue`, lifecycle dialogs in Atlas) and the *data composables for that
> plane's doctypes*. The shell, the cell renderers, the badges, the session
> boot, and the hand-off helper move into the package.

## Making the hand-off invisible (the four levers)

1. **Identical shell.** Because both apps render `FCAppShell` with the same
   espresso tokens, the sidebar/topbar are pixel-identical before and after the
   redirect. The eye registers a *content* change, not an *app* change.

2. **Warm, screenless SSO.** A signed-in Central user must never see a login
   screen on hand-off (`skip_authorization` on the cluster's OAuth client —
   already set, `spec/03`). Click → arrive.

3. **Branded transition, not a white flash.** `openInRegion()` paints a
   full-screen FC transition ("Opening Bangalore…", shell chrome already visible)
   *before* setting `window.location`, so the unload→SSO→load sequence reads as a
   route change, not a page reload.

4. **Deep-link preservation (the one required Atlas fix).** Central computes the
   canonical target deep link; Atlas must honor `redirect-to` **through** login/
   SSO so you land on the exact machine, not a generic dashboard. Today Atlas's
   `www/dashboard.py` hardcodes `redirect-to=/dashboard`, dropping the subpath —
   it must instead echo the requested path:
   ```python
   frappe.local.flags.redirect_location = f"/login?redirect-to={frappe.request.path}"
   ```
   This is the single concrete change required of Atlas for a true deep-link
   hand-off (tracked in `OPEN-QUESTIONS`).

The hand-off helper, in the shared package, is the *only* place that knows the
rule:
```ts
// frappe-cloud-ui/session/openInRegion.ts
export function openInRegion(cluster /* {base_url} */, path /* "/dashboard/machines/vm-9" */) {
  showTransition(`Opening ${cluster.cluster_name}…`)     // lever 3
  window.location.href = `${cluster.base_url}${path}`    // lever 2+4: triggers SSO, carries the path
}
```

## Routing model (domain = plane, path = resource)

```
cloud.frappe.io/dashboard/assets               Central — the global directory
cloud.frappe.io/dashboard/billing              Central — account & billing (spec/08)
bangalore.frappe.io/dashboard/machines/vm-9    Atlas Bangalore — operate the machine
        → (later) a Sites tab → Bench UI on the VM, via Atlas
```

- Both SPAs use the **same vue-router base** (`/dashboard`) so paths line up
  across planes.
- `PlaneBreadcrumb` always renders the truthful hierarchy and makes *up*
  navigation a plain link: **every Atlas page has a "Frappe Cloud" anchor home.**
  Down-navigation is the SSO redirect; up-navigation is a normal link. The user
  always knows where they are and how to get back.

## Data & interaction conventions (v1 composables)

- **Lists** render from the plane's own resources via `useList` (Central:
  `Virtual Machine` registry rows; Atlas: live `Virtual Machine`). Never a
  cross-domain `useList`.
- **Realtime** (`spec/07`): subscribe the `useList`/`listStore` to the team room
  and patch on `registry:updated`; badges subscribe per row. No polling.
- **Cold paint:** `idbStore` repaints the last-known list instantly, then the
  refetch reconciles — critical so a post-hand-off load isn't blank.
- **Mutations** (Atlas): `useDoctype().runDocMethod('start'|'stop'|'terminate')`,
  each UI control gated by the IAM resolver (`spec/06`) reading the session's
  capabilities; a billing-blocked action shows a *billing* reason, a
  permission-blocked action shows a *permission* reason — never a generic error.
- **Session:** `useSession()` reads the Jinja boot (`window.user/csrf_token/
  site_name`, plus `is_system_manager`) injected by each plane's
  `www/dashboard.py` (`spec/03`). On Atlas, the per-team capabilities come from
  the `fc_teams` token claim (`spec/06`) and the active team from the `/t/<team>/`
  path — so the UI gates each control on "does `fc_teams[pathTeam].caps` include
  this action". One `useSession` implementation, imported by both.

## What the frontend must never do

- No cross-domain API calls between planes (no CORS bridge; Central stays out of
  Atlas's path).
- No iframing or proxying of another plane's UI (`spec/04`: hand-off over
  integration).
- No second component library, no bespoke CSS framework — espresso/frappe-ui
  only.
- No copy-pasted shell/cells/session between apps — import `frappe-cloud-ui`.

## Migration plan (from today's two duplicated SPAs)

1. **Upgrade both apps to frappe-ui `v1.0.0-beta`**; swap the data layer to the
   v1 composables (`useList/useDoc/useDoctype/useCall/useNewDoc`). Mechanical;
   the API shapes are close to what Atlas/Central already use.
2. **Extract `frappe-cloud-ui`** — move `AppShell`, `ResourceList`/`StatusBadge`/
   `CopyText`/relative-time, `session`, and the espresso preset out of both apps
   into the package; both import it. (This deletes the current duplication.)
3. **Add `openInRegion()` + the branded transition**; route all
   Central→Atlas navigation through it.
4. **Fix Atlas deep-link preservation** (the `redirect-to` echo above).
5. **Add `PlaneBreadcrumb` + back-to-Central anchor** to Atlas's shell.

After step 2, a redirect between Central and Atlas renders the same chrome with
the same tokens — the apps are independent in deploy and failure, identical in
feel. That is the definition of seamless this system targets.
