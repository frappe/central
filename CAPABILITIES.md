# Capability Taxonomy

Capabilities are the authorization vocabulary of the Frappe Cloud control plane.
Central is the source of truth: it resolves a user's team grants into capability
strings and stamps them into the SSO token (`fc_teams` claim). Atlas and each
bench then enforce those strings on their own resources.

The capability set lives in [`fixtures/capability.json`](central/fixtures/capability.json)
and the default role assignments in [`fixtures/team_role.json`](central/fixtures/team_role.json).
This document is the human-readable reference for that data.

A capability is named `resource:action` and belongs to exactly one **plane**:

| Plane | Owner | Enforced in |
| --- | --- | --- |
| `central` | Central | Central (`central/permissions.py`, Team doc methods) |
| `atlas` | Atlas | Atlas API (when wired) |
| `bench` | each bench | bench `admin/backend/auth.py` (`BENCH_CAPS`) |

## Vocabulary vs. roles

The distinction matters:

- **The vocabulary** — the capability strings below — is the part that crosses
  into a bench's token and gets enforced. It is small and changes rarely.
- **Roles** (system *and* team-defined custom roles) are just *named subsets* of
  that vocabulary. A custom role recombines existing capabilities; it never mints
  a new capability string, so a bench always understands the result. Teams can
  create as many custom roles as they like without affecting this contract.

## The 27 capabilities

### `central` plane (6)

| Capability | Meaning |
| --- | --- |
| `asset:view` | View team-owned assets in the Central registry. |
| `billing:view` | View billing data. |
| `billing:manage` | Manage billing settings and payment operations. |
| `team:edit` | Edit team metadata. |
| `team:manage_members` | Invite, suspend, and change team members. |
| `team:delete` | Delete a team. |

### `atlas` plane (8)

| Capability | Meaning |
| --- | --- |
| `vm:view` | View virtual machines in Atlas. |
| `vm:create` | Create virtual machines in Atlas. |
| `vm:start` | Start virtual machines in Atlas. |
| `vm:stop` | Stop virtual machines in Atlas. |
| `vm:resize` | Resize virtual machines in Atlas. |
| `vm:snapshot` | Create, clone, and delete virtual machine snapshots in Atlas. |
| `vm:rebuild` | Rebuild virtual machines and restore snapshots in Atlas. |
| `vm:terminate` | Terminate virtual machines in Atlas. |

### `bench` plane (13)

These mirror `BENCH_CAPS` in the bench's `admin/backend/auth.py`.

| Capability | Meaning |
| --- | --- |
| `site:view` | List sites; view site detail, logs, tasks. |
| `site:create` | Create a new site. |
| `site:delete` | Drop a site. |
| `site:backup` | Trigger and download site backups. |
| `site:restore` | Restore a site from backup. |
| `site:migrate` | Run migrate and schema changes. |
| `site:config` | Edit site config (`site_config.json`). |
| `app:install` | Install and uninstall apps on a site. |
| `db:access` | Database console and query access. |
| `log:view` | View logs. |
| `task:run` | Run bench tasks and manage processes. |
| `bench:config` | Edit bench-level config. |
| `bench:manage` | Start/stop processes, run updates and upgrades. |

## The 5 system roles

System roles are seeded from `fixtures/team_role.json` and are identical across
all teams. Teams may also define custom roles scoped to themselves.

| Capability | Owner | Admin | Developer | Viewer | Billing |
| --- | :-: | :-: | :-: | :-: | :-: |
| `asset:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `billing:view` | ✓ | | | | ✓ |
| `billing:manage` | ✓ | | | | ✓ |
| `team:edit` | ✓ | ✓ | | | |
| `team:manage_members` | ✓ | ✓ | | | |
| `team:delete` | ✓ | | | | |
| `vm:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `vm:create` / `start` / `stop` / `resize` / `snapshot` / `rebuild` / `terminate` | ✓ | ✓ | ✓ | | |
| `site:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `site:create` / `site:delete` | ✓ | ✓ | | | |
| `site:backup` / `restore` / `migrate` / `config` | ✓ | ✓ | ✓ | | |
| `app:install` / `db:access` / `task:run` | ✓ | ✓ | ✓ | | |
| `log:view` | ✓ | ✓ | ✓ | ✓ | |
| `bench:config` / `bench:manage` | ✓ | ✓ | | | |

Totals: Owner 27, Admin 24, Developer 18, Viewer 4, Billing 5.

## Changing the taxonomy

The vocabulary is a contract with every deployed bench, so adding, removing, or
renaming a capability is a coordinated change, not a casual one:

1. Edit the fixtures (`fixtures/capability.json`, `fixtures/team_role.json`) and
   run `bench export-fixtures --app central` to regenerate them from the DB.
2. Update the `bench`-plane mirror (`BENCH_CAPS` and the route→capability map in
   `admin/backend/auth.py`) if a `bench`-plane capability changed.
3. Update this document.

**Never rename a capability in place.** An already-deployed bench keeps checking
the old string and will authorize the wrong thing, silently. Add the new
capability, migrate grants to it, then retire the old one.
