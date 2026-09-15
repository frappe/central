# Delivery

## Purpose

This document says how the work in [Rewrite scope](REWRITE_SCOPE.md) reaches `develop`. It gives the branch model, the pull request list, and the rules that keep each review small.

Two rules drive it.

- Each phase lands as its own group of pull requests.
- A change to `central/billing/**` is its own pull request. No functional pull request carries a billing change with it.

## Where billing meets the rewrite

Billing is 49,546 lines with 98 test files. The rewrite reaches it in only 3 places.

| Contact | Files | Phase |
|---|---|---|
| `cluster` is a Link to `Atlas Instance` | `Catalog Rate`, `Billing Scenario Rate` | 0 |
| `AtlasClient` for the capacity filter | `catalog/subscriptions.py`, `api/dashboard/catalog.py` | 2 |
| `"Asset"` and `asset_id` | 89 and 120 references | 1 |

Nothing else in billing reads a field the rewrite removes. `login_url`, `login_url_expires_at`, `last_event_at`, `atlas_task`, and `pilot_credential_id` have zero billing references. Keep the field name `cluster` in billing. It has 793 references and the rewrite gives no reason to rename it, only to change what it links to.

## Branch model

Stack the pull requests inside a phase. Merge the phase into `develop` before you open the next phase.

```text
develop
  |
  +-- rewrite/0.1-team-tenant-id            base: develop
        |
        +-- rewrite/0.2-central-ed25519-keys      base: 0.1
              |
              +-- rewrite/0.3-region-atlas-connection   base: 0.2
                    |
                    +-- rewrite/0.4-billing-region-link     base: 0.3
                          |
                          +-- rewrite/0.5-drop-atlas-instance   base: 0.4
```

Each pull request shows only its own change, because its base is the branch below it. A reviewer reads one small diff.

Stack depth stays at 5 or less. A deeper stack costs more to rebase than it saves in review.

### Commands

Create the next branch on top of the current one:

```bash
git checkout -b rewrite/0.2-central-ed25519-keys rewrite/0.1-team-tenant-id
```

Open the pull request against the branch below it:

```bash
gh pr create --base rewrite/0.1-team-tenant-id --title "feat(sso): issue Ed25519 keys and publish a namespaced key set"
```

When a review changes a lower branch, move the branches above it:

```bash
git rebase --onto rewrite/0.1-team-tenant-id <old-base-sha> rewrite/0.2-central-ed25519-keys
git push --force-with-lease
```

Merge from the bottom. GitHub moves an open pull request onto the merged branch's own base, so the next one in the stack retargets by itself.

### Patches

Every schema change adds a patch, and `scripts/check_patches.py` runs on each pull request. Patches run in the order of `patches.txt`, and a stack merges from the bottom, so the order is correct. Do not merge a stack out of order.

## The pull requests

`[atlas]` and `[pilot]` mark a pull request in another repository. `[billing]` marks one that changes `central/billing/**`.

### Phase 0. Identity and region

| # | Title | Notes |
|---|---|---|
| 0.1 | `feat(iam): add an immutable tenant identifier to Team` | The field, the allocation, and a patch for existing Teams |
| 0.2 | `feat(sso): issue Ed25519 keys and publish a namespaced key set` | The `central:` namespace, more than 1 active key, the region and proxy minters |
| 0.3 | `feat(regions): move the Atlas connection onto Region` | `Region` gains the fields and the code reads it. `Atlas Instance` still exists, so billing keeps working |
| 0.4 | `refactor(billing): link cluster to Region` | **[billing]** 2 Link options and a patch |
| 0.5 | `refactor(regions): drop Atlas Instance` | The doctype and its patch. Point `list_instances` at `Region`, rename it to `regions`, and drop its permission bypass |
| 0.6 | `refactor(iam): rename the cluster capability to region` | 1 call site, `central/iam.py`, the fixture, `CAPABILITIES.md`, the tests. Pilot does not read it |

0.3 through 0.5 accept one intermediate state, where `Region` and `Atlas Instance` both exist. That is the cost of keeping billing in its own pull request, and it is paid back within the same phase.

0.6 depends on nothing above it. Branch it off `develop` beside the stack, or land it after the phase merges, so the stack stays 5 deep.

### Phase 1. Demolition and the rename

| # | Title | Notes |
|---|---|---|
| 1.1 | `refactor(atlas): remove the event webhook and the mirror` | `central/api/atlas.py`, `Atlas Event`, the webhook gate, `central/mirror.py` |
| 1.2 | `refactor(regions): remove the tunnel and the host task runner` | `Central Tunnel Settings`, `Host Task`, `host_task.py`, `scripts_catalog.py`, `central/scripts/`, the sudoers file, `spec/TUNNEL.md` |
| 1.3 | `refactor(pilot): remove enrolment and the bootstrap token` | `enroll`, the minter, the verifier, `PilotCredential.reserve`, the Redis guard |
| 1.4 | `refactor(core): rename Asset to Server` | **[billing]** Mechanical. No behavior change. A doctype rename is atomic, so it cannot leave billing pointing at a table that is gone |
| 1.5 | `refactor(billing): bill a subject instead of an asset` | **[billing]** `asset_id` and `service_subject` become `subject_type` and `subject_name` |

1.4 is the one pull request that crosses billing without being a billing change. State that in the description, and keep the diff to a rename so a reviewer can read `git diff --stat` and sample it.

### Phase 2. The Atlas client and the image catalog

| # | Title | Notes |
|---|---|---|
| 2.1 | `feat(api): expose the memory snapshot shape on the image response` | **[atlas]** 3 fields, then regenerate `atlas-client` |
| 2.2 | `feat(central): allow a metadata base override` | **[pilot]** Makes the bootstrap testable without a machine |
| 2.3 | `feat(atlas): add the Atlas API client` | Token, tenant header, timeouts, error mapping |
| 2.4 | `feat(regions): add the image catalog` | Refreshed from `GET /api/atlas/images`, holds the Frappe version, the Pilot release, and the snapshot shape |
| 2.5 | `refactor(billing): drop the capacity filter` | **[billing]** Atlas exposes no capacity read. Removes `validate_capacity`, the filter, and 3 test modules |

2.1 merges first. 2.3 depends on it.

### Phase 3. Server lifecycle

| # | Title |
|---|---|
| 3.1 | `feat(servers): rework the Server record for the Atlas contract` |
| 3.2 | `feat(servers): reconcile server state from Atlas` |
| 3.3 | `feat(servers): rewrite create, power, resize and terminate` |

### Phase 4. Boot credential and signup

| # | Title |
|---|---|
| 4.1 | `feat(pilot): issue the boot credential into machine metadata` |
| 4.2 | `feat(sites): record a site from what Pilot reports` |

Signup works when 4.2 merges.

### Phase 5. Sites, routing, and domains

| # | Title | Notes |
|---|---|---|
| 5.1 | `feat(central): support many sites on one host` | **[pilot]** Relax `CentralSetup._alias_site` and `pilot setup central` |
| 5.2 | `feat(sites): issue a certificate for a Central-managed domain` | **[pilot]** Specify and review the contract before either side is written |
| 5.3 | `feat(regions): compute the mesh address and the automatic name` | |
| 5.4 | `feat(sites): create and rename a site through Pilot` | |
| 5.5 | `feat(domains): add Site Domain and the proxy domain map` | |

### Phase 6. Cargo and telemetry

| # | Title |
|---|---|
| 6.1 | `fix(cargo): give a Cargo host its Central address and token` |
| 6.2 | `feat(sso): sign Datum tokens with the Ed25519 key` |

### Phase 7. The typed API

| # | Title | Notes |
|---|---|---|
| 7.1 | `feat(api): add the typed API core` | Router, binding, OpenAPI, error envelope |
| 7.2 | `feat(api): serve the server lifecycle at /api/central/v1` | |
| 7.3 | `feat(api): serve signup at /api/central/v1` | |
| 7.4 | `refactor(billing): serve billing at /api/central/v1` | **[billing]** The surface only. The domain logic does not change |
| 7.5 | `build(clients): generate and check the Central API client` | Commits the document and the client, and fails on drift |

### Phase 8. Dashboard

One pull request for each screen group: server creation, server state, onboarding, sites, domains, console, and the generated client.

## Rules for each pull request

- It leaves `develop` working. Tests pass on its own branch.
- It carries its own patch when it changes a schema.
- It changes `central/billing/**` only when it is marked `[billing]`, with one exception, 1.4, which is a rename and is marked in its description.
- Its title is a Conventional Commit subject, and its description follows the template in `CLAUDE.md`.
- It updates the documentation that its change affects, in the same pull request.

## What to verify before each merge

```bash
../../env/bin/ruff check central
python3 scripts/check_patches.py
pilot frappe --site central.localhost run-tests --app central
```

Run the whole suite, including billing, on any pull request marked `[billing]` and on 1.4.
