### Central

The one stop console for Frappe Cloud

### IAM slice

Central currently owns the IAM authority layer:

- `Capability` is the append-only action catalog.
- `Team Role` bundles capabilities. System roles ship as fixtures: `Owner`,
  `Admin`, `Developer`, `Viewer`, and `Billing`.
- `Team` owns `Team Member` rows. A user's effective grants resolve only through
  `Team Member -> Team Role -> Role Capability -> Capability`.
- New enabled users are bootstrapped with `Central User`, one default
  team, and an active `Owner` team membership.
- `fc_teams` is added to Frappe OAuth/OpenID userinfo by `central.oauth`.
- `IAM Permission Probe` lets an operator test a `(user, team, capability)` tuple
  from Desk before Atlas enforcement is wired.

Atlas UI and lifecycle enforcement are intentionally deferred. Atlas should read
`fc_teams` into the session on SSO, add `Virtual Machine.team`, use
`/dashboard/t/<team>/...` routes, and gate VM methods from the local session.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app central
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/central
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

agpl-3.0
