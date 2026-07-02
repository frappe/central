# Central

Central is the control plane for Frappe Cloud. It owns identity, Teams, roles,
capabilities, billing catalog, subscriptions, invoices, and the local mirror of
resources that run on Atlas.

Atlas is the regional runtime. One Atlas site represents one region or cluster.
Central calls Atlas to create and operate VMs/sites, and Atlas reports lifecycle
events back to Central. Atlas does not own Team membership, billing state, or IAM
policy.


Important contracts:

- Central writes authority. Atlas reads authority.
- `Team Member -> Team Role -> Capability` is the only customer permission path.
- `Atlas Instance` stores the regional Atlas URL and admin credentials Central
  uses for operator calls.
- Production Atlas registration uses the WireGuard tunnel flow in
  [spec/TUNNEL.md](spec/TUNNEL.md).
- Local development uses `Atlas Instance.skip_tunnel = 1`; it pushes the scoped
  Central service user to Atlas but keeps traffic on `atlas_base_url`.

## Local Setup

Use a fresh bench when possible. A new pilot/bench-cli bench is preferred over an
existing shared development bench because Central and Atlas both install fixtures,
background jobs, demo data, and local site configuration.

Link to pilot - https://github.com/frappe/pilot

The examples below assume:

- Central site: `central.localhost`
- Atlas site: `mumbai.atlas.localhost`
- Admin password: `admin`
- Apps are checked out as `central` and `atlas`

Create or use a fresh bench, then install both apps on separate sites:

```bash
bench get-app central <central-repo-url>
bench get-app atlas <atlas-repo-url>

bench new-site central.localhost --admin-password admin
bench --site central.localhost install-app central

bench new-site mumbai.atlas.localhost --admin-password admin
bench --site mumbai.atlas.localhost install-app atlas

bench set-config -g developer_mode 1
bench --site central.localhost migrate
bench --site mumbai.atlas.localhost migrate
```

If your bench does not have a global DB root password configured, `bench new-site`
will ask for one or you can pass `--db-root-password <password>`.

Start the bench in another terminal:

```bash
bench start
```

Open:

```text
http://central.localhost:8000/app
http://mumbai.atlas.localhost:8000/app
```

## Seed Central

Run the Central local bootstrap:

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local
```

This command only runs with `developer_mode` enabled. It seeds useful local data:

- billing catalog, plans, rates, gateways, and trust tiers
- demo Teams and Team members
- invoices, subscriptions, payment methods, wallets, and notifications
- billing workspace data

The demo users are roster data, not login fixtures. Use `Administrator` for Desk
inspection, or set passwords manually for specific users.

To reseed without touching Atlas registration:

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local --kwargs '{"register_atlas":0}'
```

## Wire Atlas Locally

On the Atlas site, generate an Administrator API key and secret from Desk:

```text
User > Administrator > API Access > Generate Keys
```

Then run Central's bootstrap with those Atlas admin credentials:

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local --kwargs '{"region":"in-mumbai","atlas_base_url":"http://mumbai.atlas.localhost:8000","atlas_api_key":"<atlas-admin-api-key>","atlas_api_secret":"<atlas-admin-api-secret>"}'
```

This creates or updates the `Atlas Instance` row for `in-mumbai`, marks it as
local-dev `Skip Tunnel`, registers the scoped Central service user on Atlas, and
keeps Central-to-Atlas calls on `http://mumbai.atlas.localhost:8000`.

For a fake Atlas fleet that does not touch a cloud provider, use Atlas's fake
provider demo on the Atlas site:

```bash
bench --site mumbai.atlas.localhost execute atlas.atlas.demo.run --kwargs '{"reset": true}'
```

For real provider bootstrap, follow [../atlas/BOOTSTRAP.md](../atlas/BOOTSTRAP.md).
That path creates billable infrastructure.

## Useful Test Data

The compact Central seed creates Teams for:

```text
northwind
daybreak
harbor
rivulet
seedling
```

Each seeded Team has users shaped like:

```text
owner-<team>@example.com        Owner
admin-<team>@example.com        Admin
dev-<team>@example.com          Developer
billing-<team>@example.com      Billing
viewer-<team>@example.com       Viewer
contractor-<team>@example.com   Developer, Suspended
invitee-<team>@example.com      Viewer, Invited
finance-<team>@example.com      Finance & Ops custom role
```

## Tests

Run the Central test suite from the bench root:

```bash
bench --site central.localhost run-tests --app central
```

Run the focused developer setup tests:

```bash
bench --site central.localhost run-tests --app central --module central.tests.test_developer_setup
```

## License

agpl-3.0
