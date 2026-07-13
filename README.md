# Central

Central is the new control plane for Frappe Cloud v2. It
manages IAM, billing, add-ons and other services.
The regional VM runtime is managed and operated by [Atlas](https://github.com/frappe/atlas).

## Requirements

- Python 3.14
- Node.js 24 and Yarn
- MariaDB 11.8 and Redis 6+
- [Frappe Bench](https://docs.frappe.io/framework/user/en/installation)

The Frappe installation guide covers the system dependencies and Bench setup.

## Local development

The commands below create a fresh Bench and a Central site. Run them from the
Bench root.

```bash
bench get-app central https://github.com/frappe/central.git
bench setup requirements --dev

bench new-site central.localhost --admin-password admin
bench --site central.localhost install-app central
bench --site central.localhost set-config developer_mode 1
bench build --app central
```

If MariaDB requires a root password, add `--db-root-password <password>` to
`bench new-site`.

Start the Bench:

```bash
bench start
```

Open Central at <http://central.localhost:8000/app> and sign in as
`Administrator` with password `admin`.

### Seed demo data

Enable developer mode before running the local bootstrap. It creates sample
teams, users, billing records, and catalog data.

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local
```

To reseed without registering Atlas:

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local \
  --kwargs '{"register_atlas": 0}'
```

### Run Atlas locally (optional)

Install Atlas on a second site when you need to test Central-to-Atlas flows:

```bash
bench get-app atlas https://github.com/frappe/atlas.git

bench new-site mumbai.atlas.localhost --admin-password admin
bench --site mumbai.atlas.localhost install-app atlas
bench --site mumbai.atlas.localhost migrate
```

Generate an Administrator API key and secret in Atlas at
`User > Administrator > API Access > Generate Keys`, then register the local
Atlas site with Central:

```bash
bench --site central.localhost execute central.api.developer_setup.setup_local \
  --kwargs '{"region":"in-mumbai","atlas_base_url":"http://mumbai.atlas.localhost:8000","atlas_api_key":"<atlas-api-key>","atlas_api_secret":"<atlas-api-secret>"}'
```

For a provider-free Atlas demo fleet:

```bash
bench --site mumbai.atlas.localhost execute atlas.atlas.demo.run --kwargs '{"reset": true}'
```

See the [Atlas bootstrap guide](https://github.com/frappe/atlas/blob/main/BOOTSTRAP.md)
for real provider setup. It creates billable infrastructure.

## Frontend development

The primary console is in `console/`. The older dashboard remains in
`dashboard/` while it is being migrated.

```bash
cd apps/central
yarn install
yarn dev              # primary console
yarn dev:legacy-dashboard
```

For a production-style build served by Frappe:

```bash
yarn build
bench build --app central
```

## Tests

Run the Python test suite from the Bench root:

```bash
bench --site central.localhost run-tests --app central
```

Run the focused local bootstrap tests:

```bash
bench --site central.localhost run-tests \
  --app central --module central.tests.test_developer_setup
```

The end-to-end suite requires a running Bench and payment-gateway test keys.
See [`e2e/README.md`](e2e/README.md) for setup and commands.

## Documentation

- [IAM](spec/IAM.md)
- [Capabilities](CAPABILITIES.md)
- [Atlas tunnel](spec/TUNNEL.md)
- [Execution plan](spec/EXECUTION_PLAN.md)

## Related projects

- [Atlas](https://github.com/frappe/atlas) — regional runtime
- [Pilot](https://github.com/frappe/pilot) — local and remote Bench management

## License

[AGPL-3.0](license.txt)
