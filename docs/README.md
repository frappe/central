# Frappe Cloud documentation

## Purpose

This folder holds the customer documentation site for Frappe Cloud. It uses VitePress 1.6.4 with the Frappe UI 1.0.1 docs theme and the Espresso design system. Keep the Frappe UI version the same as the dashboard. The theme entry is marked unstable, so review theme changes when you update it.

| Path | Holds |
| --- | --- |
| `content/` | Pages. One folder per sidebar group. |
| `content/public/media/{light,dark}/` | Screenshots (`.webp`) and recordings (`.mp4` with a `.webp` poster), one file per theme. |
| `.vitepress/` | Site configuration, sidebar, and theme components. |
| `capture/` | The demo seed and the scripts that capture media from the real console. |

Do not put operator procedures, internal hostnames, or credentials in these pages. The operator handbook is a separate site.

## Development

```bash
cd docs
yarn install
yarn dev
```

Open `http://localhost:5173`. Set `DOCS_BASE` when the host serves the site below a path, such as `DOCS_BASE=/cloud/ yarn build`.

## Configuration

| Setting | Location | Example |
| --- | --- | --- |
| Console URL for the **Open console** link | `consoleUrl` in `.vitepress/config.mts`. The link is hidden while it is empty. | `https://cloud.example.com/dashboard` |
| Base path | `DOCS_BASE` environment variable at build time | `/central/` |

## Publication

`.github/workflows/docs.yml` builds the site and publishes it to GitHub Pages at `https://frappe.github.io/central/`. It runs on a push to `develop` that changes `docs/`, and on demand from the Actions tab.

Before the first run, a repository admin sets **Settings > Pages > Build and deployment > Source** to **GitHub Actions**.

## Demo data

All media comes from the real console on a local site, `docs.localhost`, filled with fictional data. The team is Contrail Coffee. Its owner is Zara Quill. It runs 12 servers in Mumbai (`bom`).

1. Create the site and mark it as a documentation site. The seed refuses to run on any other site, because the billing demo it reuses deletes all billing and server rows.

   ```bash
   pilot new-site docs.localhost --apps central
   pilot frappe --site docs.localhost set-config docs_demo_site 1
   pilot frappe --site docs.localhost set-config pause_scheduler 1
   ```

2. Seed the data from `docs/capture`. Use `--overlay-only` to keep billing data and redo only the team, servers, sites, keys, and snapshots.

   ```bash
   cd docs/capture
   ../../../../env/bin/python -m seed
   ```

3. Serve the site on its own port. The bench web server serves only its default site.

   ```bash
   cd sites
   ../env/bin/python -c "import frappe.app; frappe.app.serve(port=8010, sites_path='.', no_reload=True)"
   ```

4. Build the dashboard once, so the server has current console assets: `cd dashboard && yarn build`.

Sign in at `http://docs.localhost:8010/dashboard` as `zara@contrail.example` with the password `docs@2026`.

### Pilot demo bench

Pilot screenshots come from a separate bench, `docs-pilot`, on Frappe version 16. It runs `erp.bom.frappe.cloud` with ERPNext and `chat.bom.frappe.cloud` with Raven.

Pilot adds a backup job to the host user's crontab for each new site. Run the setup commands with `capture/bin/crontab` first on `PATH`, so these jobs go to a file and your own crontab stays unchanged.

```bash
export DEMO_CRONTAB=<benches>/docs-pilot/config/demo-crontab
export PATH=<central>/docs/capture/bin:$PATH
pilot --yes new docs-pilot --database mariadb --admin-password 'Docs@2026'
pilot --yes -b docs-pilot init
pilot --yes -b docs-pilot get-app https://github.com/frappe/erpnext --branch version-16
pilot --yes -b docs-pilot get-app https://github.com/frappe/raven --branch main
pilot --yes -b docs-pilot new-site erp.bom.frappe.cloud --admin-password 'Docs@2026'
pilot --yes -b docs-pilot new-site chat.bom.frappe.cloud --admin-password 'Docs@2026'
pilot -b docs-pilot start
pilot --yes -b docs-pilot install-app erp.bom.frappe.cloud erpnext
pilot --yes -b docs-pilot install-app chat.bom.frappe.cloud raven
```

In `docs-pilot/bench.toml`, set `onboarding = "dismissed"` and `allow_developer_mode = true` under `[bench]`. Run `pilot admin build` once, so the Admin UI is current. The Pilot Admin is at `http://localhost:7003` with the password `Docs@2026`. It allows 5 sign-ins a minute.

Back up each site once from its **Backups** tab, so the **Tasks** page has entries. Do not add SSH keys in this Pilot, because Pilot writes them to the host user's `authorized_keys`.

## Media capture

```bash
node capture/run.mjs                  # every scene, both themes
node capture/run.mjs servers/create   # scenes whose name contains the filter
```

Each file in `capture/scenes/` exports a list of scenes. A scene captures the console at 1280 × 800 in the light and the dark theme.

| Field | Meaning |
| --- | --- |
| `name` | Output path under `media/<theme>/`, such as `servers/list`. |
| `app` | Optional. `pilot` captures the Pilot Admin of the `docs-pilot` bench at `http://localhost:7003`. Without it, the scene captures the console. |
| `path` | Console path after `/dashboard`, or a Pilot path such as `/sites`. A console path can be a function that receives `{ team, servers }`, where `servers` maps a server title to its ID. |
| `target` | Optional CSS selector. The shot crops to this element with a 16 px margin. Without it, the shot is the full viewport. |
| `setup(page, data)` | Optional. Puts the page in the state to capture, such as an open dialog. |
| `steps(studio, page, data)` | Makes the scene a recording. Use `studio.click(locator)`, `studio.type(locator, text)`, `studio.moveTo(locator)`, `studio.wait(ms)`, and `studio.zoomOut()`. The camera zooms to each click and typing target. |

```js
export default [
	{ name: 'servers/list', path: '/servers' },
	{ name: 'servers/header', path: ({ servers }) => `/servers/${servers['erp-production']}`, target: 'header:has(h1)' },
]
```

The frame is the same for every file: a theme gradient, 28 px padding, a 10 px radius, an edge line, and a soft shadow. Capture both themes from one scene, never by hand.

`capture/fixtures.mjs` answers the reads that differ from a real Frappe Cloud server. In the console, these are server metrics and the image list, which need a live region. In Pilot, these are storage (scoped to the bench's own databases), domains and their DNS records, wildcard domains, and SSH keys. A failed scene does not stop the run, and the run exits with an error at the end.

## Writing

Write in ASD-STE100 Simplified Technical English. Follow Stripe and Railway: short, literal, and direct.

### Page types

| Type | Starts with | Contains |
| --- | --- | --- |
| Concept | A one-sentence definition: "A server is ..." | One H2 per idea, a table for states or options, a Limits section with numbers. |
| Quick start | "This guide shows how to ..." | Before you begin, numbered H2 stages, one visual per stage, What next. |
| How-to | One sentence: what the task does and when to use it. | Who can do it, numbered steps, the result, recovery. |

End every page with **See also** (3 to 5 links) or **What next** (a bold link and a short phrase).

### Sentences

- One idea per sentence. 20 words at most, 25 in a numbered step.
- Active voice, present tense. Address the reader as "you". Write steps in the imperative.
- One action per numbered step. Two clicks on the same screen can share a step.
- Name the place, then the action: "Go to **Servers**. Click **New server**."
- Write console labels in **bold**, exactly as the console shows them. Use **Settings > SSH keys** for a path.
- Write values, commands, states, and hostnames in `code`.
- Use sentence case for headings. A task heading is a verb phrase: "Take a snapshot". A concept heading is a noun: "Regions".
- Use one term for one thing: server (not VM, instance, or machine) in the console pages. Define a term once and link to it.
- State limits as facts with numbers. Do not write "may", "might", "simply", "just", or "easy".
- Put the consequence before an irreversible step: "This deletes the disk. You cannot undo this."
- Use at most 2 callouts on a page: `::: info` for a role or plan condition, `::: warning` for data loss or cost.
- Keep a paragraph to 3 sentences. Use a list for 3 or more parallel items, and a table for options or comparisons.
- Describe current behavior only. Do not write "new" or "coming soon".
- Keep each paragraph on one source line. Do not use em dashes.

### Visuals

Show what is easier to see than to read.

- Use `<Screenshot name="servers/list" alt="..." />` after the sentence that introduces it. Write `alt` text that names the screen and what it shows.
- Use `<Clip name="servers/create" alt="..." />` for a flow of more than 3 steps on one screen.
- Use a table, not an image, for anything a reader copies or compares.
- Use `<Airport code="bom" />` when the text names a region code.
- Use `<Cards>` with `<Card title link icon="lucide-...">` for landing pages and next steps.

Verify each statement against the dashboard source in `dashboard/src` and the owning specification in `spec/`. Do not infer an action from an API name.

## Validation

```bash
yarn build
```

The build fails on a dead link or a Markdown error. Then check search, navigation, both themes, and a 375 px width in `yarn preview`.
