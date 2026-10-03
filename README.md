# Central

Central is the control plane for Frappe Cloud V2. It signs people in, decides what each team member can do, creates servers through Atlas, and bills each team. It is a Frappe app with a Vue console in `dashboard/`.

Central does not run servers. [Atlas](https://github.com/frappe/atlas) runs the virtual machines in each region, [Pilot](https://github.com/frappe/pilot) runs the benches and sites on a server, and Cargo builds the server images. See [Integrations](spec/INTEGRATIONS.md) for the contracts.

## Requirements

Python 3.14, Node.js 24 with Yarn, MariaDB 11.8, Redis 6 or later, and [Pilot](https://github.com/frappe/pilot).

## Set up a local site

Run these commands from the bench root:

```bash
pilot get-app https://github.com/frappe/central.git --branch develop
pilot new-site central.localhost --admin-password admin
pilot install-app central.localhost central
pilot frappe --site central.localhost set-config developer_mode 1
NO_PROXY='*' pilot start
```

Open the console at `http://central.localhost:<http_port>/dashboard` and Desk at `/app`. The port is `http_port` in `bench.toml`. On macOS, `NO_PROXY='*'` stops the system proxy lookup from killing background workers.

Put gateway and integration keys in `sites/common_site_config.json`. Never commit them.

| Key | Needed for |
|---|---|
| `stripe_secret_key`, `stripe_publishable_key` | Stripe charges and top-ups |
| `razorpay_key_id`, `razorpay_key_secret` | Razorpay charges and top-ups |
| `entitlement_private_key` | Signed plan entitlements |
| `erpnext_url`, `erpnext_api_key`, `erpnext_api_secret` | Invoice sync to ERPNext |

To create servers, connect a Region to Atlas. See [Region](central/infrastructure/doctype/region/SPEC.md).

## Seed demo data

The demo seed creates ten teams with plans, subscriptions, and invoices. It deletes all billing data and all server records first. Run it only on a local site.

```bash
pilot frappe --site central.localhost execute central.billing.demo.demo_scenarios.seed
```

See the [billing demo](central/billing/demo/README.md) for the teams and logins.

## Develop the console

```bash
yarn install
yarn dev
```

## Run checks and tests

Run the linters from `apps/central`:

```bash
../../env/bin/ruff check central
../../env/bin/ruff format central
python3 scripts/check_patches.py
pre-commit run --all-files
```

Run tests on a separate site with `allow_tests` set, because some billing tests commit their data:

```bash
pilot frappe --site central-test.localhost set-config allow_tests true
pilot frappe --site central-test.localhost run-tests --app central
```

See [`e2e/README.md`](e2e/README.md) for the Playwright suite.

## Documentation

- [CLAUDE.md](CLAUDE.md): contributor and agent rules.
- [Specification router](spec/README.md): every module and cross-cutting specification.
- [Billing architecture](central/billing/ARCHITECTURE.md): the billing code map.

## License

[AGPL-3.0](license.txt)
