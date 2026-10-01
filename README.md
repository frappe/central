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

### Seed demo data (optional)

The billing demo creates ten sample teams with users, catalog, billing records, and invoices. It deletes all existing billing data first, so run it only on a local site.

```bash
pilot frappe --site central.localhost execute central.billing.demo.demo_scenarios.seed
```

See the [billing demo](central/billing/demo/README.md) for the teams it creates.

### Run Atlas locally (optional)

Install Atlas on a second site when you need to test Central-to-Atlas flows:

```bash
bench get-app atlas https://github.com/frappe/atlas.git

bench new-site mumbai.atlas.localhost --admin-password admin
bench --site mumbai.atlas.localhost install-app atlas
bench --site mumbai.atlas.localhost migrate
```

Initialize Central's Atlas and Pilot signing keys in Central SSO Settings, and configure the Atlas public key URL in Atlas Settings. Read the numeric region ID from Atlas Settings. Then, in Central's Desk, open or create the Region (for example `in-mumbai`):

1. Set **Base URL** to `http://mumbai.atlas.localhost:8000` and **Atlas Region ID** to the verified region ID.
2. Set **Status** to Active and save.
3. Click **Test Connection**, then **Enroll Atlas**.

Central accepts plain `http` only for a `localhost` host while developer mode is on. Local VM tests require an active Metal Server and available System images. Installing Atlas alone does not provide VM capacity. See the [regional configuration](central/infrastructure/doctype/region/SPEC.md) and [validation requirements](spec/LOCAL_ENVIRONMENT.md).

## Frontend development

The console lives in `dashboard/`.

```bash
cd apps/central
yarn install
yarn dev
```

For a production-style build served by Frappe:

```bash
yarn build
bench build --app central
```

## Tests

Run the Python test suite from the Bench root:

```bash
bench --site central-test.localhost run-tests --app central
```

Run one module while you work:

```bash
bench --site central-test.localhost run-tests \
  --app central --module central.tests.test_resource_actions
```

Run tests on a separate test site. Some billing tests commit their data.

The end-to-end suite requires a running Bench and payment-gateway test keys.
See [`e2e/README.md`](e2e/README.md) for setup and commands.

## Documentation

- [Agent and contributor rules](CLAUDE.md)
- [IAM](spec/IAM.md)
- [Capabilities](CAPABILITIES.md)
- [Execution plan](spec/EXECUTION_PLAN.md)

## Related projects

- [Atlas](https://github.com/frappe/atlas) — regional runtime
- [Pilot](https://github.com/frappe/pilot) — local and remote Bench management

## License

[AGPL-3.0](license.txt)
