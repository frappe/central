# Central Console (frappe-ui)

The team-facing console for the Central app — Billing, Team & Identity, and Atlas
screens, built with [frappe-ui](https://github.com/frappe/frappe-ui). Specs:
`billing-ui.md` and `central-console-ui.md`.

## Develop

```bash
cd dashboard
yarn install
yarn dev        # Vite dev server, proxies /api to the Central bench site
```

## Build

```bash
yarn build      # outputs to ../central/public/legacy-dashboard
```

The previous UI is served at `/legacy-dashboard` while its surfaces are migrated
to the new `/dashboard` application.

## Layout

- `src/utils/` — `money.js` (minor-unit display), `status.js` (`statusTheme`).
- `src/composables/` — `useCapabilities` (capability IAM gate), `useTeam`.
- `src/api/` — endpoint path constants.
- `src/components/` — shared shell + list/detail primitives.
- `src/pages/billing|team|atlas/` — the three sidebar groups.
