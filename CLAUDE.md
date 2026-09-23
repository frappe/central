# Central Repository Guide

## Session continuity

- Treat this file as the primary instruction source for every task in this repository.
- After context compaction, summarization, restart, or loss of working context, read this file again before you continue.
- Preserve a reference to `CLAUDE.md` in a handover or context summary so the next context reloads it.
- Do not rely on remembered repository rules when this file is available.

Central is the control plane for Frappe Cloud v2. It owns identity, teams, capabilities, regions, catalog, billing, and managed services. It contains a Frappe app and a Vue dashboard.

## Start here

Read the [README](README.md) for setup and local development. Read [`spec/README.md`](spec/README.md) for the specification router, and read the matching specification before you make a structural change.

- [IAM](spec/IAM.md): identity, permissions, and Atlas enforcement.
- [Capabilities](CAPABILITIES.md): the authorization vocabulary and its plane split.
- [Atlas coordination](spec/ATLAS_COORDINATION.md): the cross-repository contract.
- [Refactor backlog](spec/refactor_todo.md): the remaining pre-1.0 cleanup work.

## System boundaries

Central is one of three main repositories for cloud v2. Keep behavior in the repository that owns it.

```text
Central    control plane: identity, teams, capabilities, catalog, billing, regions
   |  HTTP + signed tokens
   v
Atlas      regional runtime: VMs, network, proxy. One instance per region.
   |
   v
Pilot      server runtime: benches, sites, apps on a single server.
```

- Central decides every `server:*` capability itself. A region only checks that a signed request's tenant matches the resource's tenant; a bench checks the scope on its own signed token. Neither holds a capability model of its own.
- Central reaches Atlas, Pilot, and Cargo only through the clients in `central/integrations/`. Do not call a remote plane from a controller, an API route, or a page.
- `Virtual Machine` is Central's server record. Central owns its identity, title, plan, image and billing links. A region only reports state back, and the integration layer applies that through `VirtualMachine.record_observed_state`.

## Scope

Central runs today:

- Identity and access: teams, members, invitations, team roles, capabilities, and the permission probe.
- Tokens: SSO and OAuth minting for Atlas, for a Pilot bench, and for Cargo, Datum and for any other future services, plus site login.
- Regions: Atlas instance registration.
- Resources: `Virtual Machine` for a provisioned server, `Site` for a self-serve site. Only the integration layer records observed state on them.
- Provisioning: provisioning requests and resource actions against Atlas and Pilot.
- Managed services: add-on catalog, LLM models and plan policies, storage backends, and service credentials.
- Notifications: event types, team notifications, user preferences, and the delivery engine.
- Billing: catalog, subscriptions, invoicing, payments, credits, and projections.
- Partners: partner membership, passport registration, and Connect credentials.
- The console in `dashboard/`.

Central plans to add:

- One `SPEC.md` per module, written as each module is rewritten.
- The remaining capability and enforcement work in [`spec/EXECUTION_PLAN.md`](spec/EXECUTION_PLAN.md).
- A repository layout redesigned from first principles, to match the current Atlas and Pilot boundaries.

`central/billing/**` is out of scope for the rewrite. Change it only when the task names it, and keep the change as small as the task needs.

## Core principles

- Keep changes small, direct, and in the module that owns the behavior.
- Keep decision-making visible to the user. Before implementation, explain the proposed design, assumptions, ownership, state, dependencies, error flow, risks, and important trade-offs. Use a small ASCII diagram when it helps. Proceed after the user agrees with the plan.
- Build the minimum working change, then iterate. Delete before you add when existing code can be simplified.
- For a bug fix, find the root cause before you change code.
- Do not change unrelated dirty files, generated artifacts, or local data.
- Do not add plan files such as `plan_*.md`. Put planned work in `spec/`.
- Do not commit secrets, private keys, tokens, `.env` content, or production credentials.
- Use `git mv` when you intentionally move or rename a tracked file.

## Temporary rules

Central is in active development and is not deployed to production.

- Do not preserve backward compatibility unless the task or specification requires it.
- Prefer the target design over compatibility layers, migration shims, deprecated aliases, or fallback behavior.
- Do not design for rolling upgrades, mixed-version deployments, or zero-downtime migration unless required.
- Revisit these rules before the first production deployment.

## Permissions

Central is the authorization source for the whole control plane. Treat every permission change as security-sensitive.

Access is team-based, not document-based. A user never holds a grant on a document. A user holds a role in a Team, the role carries capabilities, and a document is reachable because it belongs to a Team the user holds the right capability in.

```text
User -> Team Member -> Team Role -> Role Capability -> Capability ("server:view")
                                                            |
Document (.team field) -------------------------------------+
```

- Resolve every decision through `central/iam.py`. Use `can(user, team, capability)`, `get_user_team_names_with_capability`, and `resolve_team`. Do not read Team Member, Team Role, or Role Capability rows anywhere else.
- Give every team-scoped DocType an indexed `team` link field. A document without a team is unreachable by design, and a query condition must return `1 = 0` rather than fall open.
- Scope a list with the team set for the capability, not with team membership alone. Two users in the same Team can differ on `server:view`.
- Keep `System Manager` as the only operator bypass, through `user_has_operator_bypass`.
- Add a capability to `CAPABILITIES.md` and the fixtures in the same change. Never invent a capability string at a call site.

### Enforce in both layers

Every team-scoped DocType needs a `permission_query_conditions` entry and a `has_permission` entry, wired in `hooks.py` and named `<doctype>_query_conditions` and `<doctype>_has_permission`. A query condition alone still leaks a single document by name. A `has_permission` alone still leaks the list. Reuse `_team_field_query_conditions` and `_team_field_has_permission` instead of writing a new pair by hand.

An API route may still check `can(...)` before it acts, because a route must fail with a clear message and must gate writes. That check is a second layer, not the only one. Do not let it become the only thing standing between a user and another team's data.

- Use `frappe.get_list` when the read serves a request on behalf of a user. It applies the query conditions, so the framework enforces the team boundary even when a route forgets to.
- Use `frappe.get_all` only on a system path: a patch, a background job, a scheduled task, the integration layer, a test, or a read that runs as the system rather than as a user. Keep the explicit `team` filter there as well.
- Do not reach for `ignore_permissions=True`. Model the roles and capabilities correctly instead. When a call must bypass permissions, put one comment line above it that states why.
- Give each permission function a short docstring that lists its rules in order, one numbered rule per line.
- Add a test in `central/tests/` for every new rule, including the denial case and the cross-team case.

## Desk and operations

The console serves customers. Desk serves the operator who has to answer a page at 2 am. Build every DocType so that person can read it, find it, and act on it without the console and without a shell.

### Make the list usable

- Mark the hot columns `in_list_view`: the identity, the owning Team, the state, and the one number or timestamp that says whether the record is healthy.
- Mark the fields an operator filters on `in_standard_filter`: status, team, region or cluster, and type.
- Index the fields that the list filters and sorts on. Add them in the controller's `on_doctype_update`, not in a patch.
- Set a meaningful `title_field` and `search_fields`. An operator searches by the name a customer gives them, not by a hash.
- Give a state field an indicator colour so the list reads at a glance.

### Make the form readable

- Group fields into tabs and sections that follow the operator's task, not the table order. A form that is one flat column of 40 fields is a defect.
- Put identity and state at the top. Put credentials, raw payloads, and debug fields in a collapsed section or a separate tab.
- Label a field with what it means to a person. Set a description on any field whose meaning is not obvious from the label.
- Mark a field read-only when only the system writes it. An observed field must never look editable.

### Make it navigable

- Add dashboard connections to every DocType an operator would follow next. From a Team reach its sites, servers, and invitations. From a Virtual Machine reach its actions, tasks, and events. An empty `links` array on a hub DocType is a gap.
- Link related records with a Link field rather than a plain text identifier, so the connection is reachable in both directions.

### Make it actionable

- Add a desk Action button in the DocType client script for any operation an operator performs by hand today. Retry a failed task, resend an invitation, force a reconcile, rotate a credential, cancel a stuck provisioning request.
- Show the button only when the action is valid for the current state and the current user, and confirm anything destructive.
- Put the behavior in the server method that owns it and let the button call it. The button is a trigger, not a place for logic.
- Surface failure where the operator is looking. A failed background task must leave a readable error on the record, not only in a log.

## Code style

### All code

- Choose clear code over clever code. Prefer explicit configuration over implicit behavior.
- Use complete words for names. Avoid abbreviations.
- Put behavior with the module, domain object, or DocType controller that owns it.
- Use standard Frappe APIs and existing repository helpers before you add custom logic or a dependency.
- Keep functions small. About 25 lines is a useful target, not a reason to split readable code.
- Put blank lines between logical code blocks in a function.
- Use a comment of 1 or 2 lines where the purpose needs explanation. Explain why, not how.
- Keep cyclomatic complexity at 8 or less. Keep files between 100 and 500 lines when practical.
- Extend an existing folder before you add a new one. Group related files instead of adding more same-prefix modules.
- Do not add generic `utils`, `helpers`, `common`, or `misc` folders.
- Keep one owner for state that can drift. Keep temporary state inside the object or module that owns its lifecycle.
- Fail near the cause. Do not hide corrupt or partial state behind a broad fallback. Retry only operations that are safe to repeat.
- Do not add comments that repeat the code. Explain a business rule, invariant, external quirk, or concurrency rule only when the code cannot show it.
- Do not put an explanatory comment at the top of a file. Use a short class or function docstring.
- Add focused tests for changed behavior and failure cases. Do not add tests only to raise coverage. Keep tests deterministic and independent.
- Follow DRY, SOLID, and KISS. Apply them to remove real duplication and real coupling, not to add layers.

### Python

- Target Python 3.14 and Frappe v16.
- Keep domain behavior in the DocType controller, service module, or task that owns it. Keep `central/api/` routes and `hooks.py` entries thin.
- Use type hints for public functions and important data structures.
- Raise specific exceptions. Handle only errors that the code can recover from. Use `central/errors.py` for a failure that a person reads.
- Prefer standard Frappe APIs and built-in DocTypes over custom machinery. Use `frappe.db` and `frappe.qb` instead of raw SQL.
- Wrap every user-facing string in `_()`.
- Avoid mutable global state, circular imports, and lazy re-exports in a package `__init__.py`.
- Use `@property` only for a cheap, side-effect-free, no-argument operation that returns one noun-like value. Use `get_<what_it_returns>()` for an operation with arguments or multi-step work.
- Name boolean properties and methods with `is_` or `has_`.
- Keep a method public when a caller outside its owner uses it. Use a leading underscore for raw parsing, security-sensitive validation, or genuinely internal details. Do not make a method private only because it has one caller.
- Use binary units and name a field for its unit, such as `disk_mib`.
- Do not reach for `ignore_permissions=True`. Model the roles and capabilities correctly instead. When a call must bypass permissions, put one comment line above it that states why.
- Use `frappe.qb` with a join when a read spans more than 2 tables. Do not loop a query per row. No N+1 queries.
- Add indexes and unique constraints in the controller's `on_doctype_update`, not in a patch.

#### Prefer controller lifecycle hooks over API wiring

Read the [Frappe controller docs](https://docs.frappe.io/framework/user/en/basics/doctypes/controllers) before adding a step that reacts to a document reaching a state. When a document follows a lifecycle, put each step in the controller hook that owns that point in the lifecycle, not as a sequence of calls an API route or integration function makes by hand. The common hooks, in the order Frappe calls them:

| Hook | Runs | Use it for |
|---|---|---|
| `before_validate` | Before `validate`, on every save | Normalize input before it is checked |
| `validate` | Before every save | Enforce invariants; block the save on failure |
| `before_insert` | Once, before the first save | Set a field a fresh document alone needs |
| `after_insert` | Once, right after the first save | Kick off what only a newly created document triggers |
| `on_update` | After every save | React to any change, not only creation |
| `on_trash` | Before delete | Clean up what the document owns |

A route stays a thin trigger: it builds the document and calls `insert()` or `save()`, and the controller's hooks do the rest. This keeps a lifecycle step discoverable from the doctype that owns it instead of buried in whichever route happened to create the document, and it means every path that creates the document (an API route, a patch, a test) gets the same behavior for free.

```python
# Before: the API route wires each step it thinks a new Site needs.
@frappe.whitelist()
def create_trial_site(subdomain: str, team: str) -> dict:
    site = frappe.get_doc({"doctype": "Site", "subdomain": subdomain, "team": team})
    site.insert()
    notify_team_of_new_site(site)  # easy to forget on the next caller
    return {"name": site.name}


# After: Site.after_insert owns it. Any caller that inserts a Site gets the
# same behavior, and the route no longer needs to know what a new Site does.
class Site(Document):
    def after_insert(self) -> None:
        notify_team_of_new_site(self)


@frappe.whitelist()
def create_trial_site(subdomain: str, team: str) -> dict:
    site = frappe.get_doc({"doctype": "Site", "subdomain": subdomain, "team": team}).insert()
    return {"name": site.name}
```

### Dashboard

Use Vue 3, TypeScript, and Frappe UI with the Espresso design system.

Organise components in three tiers, and group a feature by domain folder instead of by name prefix.

```text
dashboard/src/components/common/      Domain-agnostic primitives: avatar, loader, skeleton, form field
dashboard/src/components/layout/      Structural chrome: sidebar, drawer, heading, empty state, banner
dashboard/src/components/<feature>/   Feature components, one folder per domain
```

- What can be a common component must be a common component. Move a repeated table action, dialog, empty state, or mutation runner out of the page.
- Keep a page thin. A page composes components and reads a composable. It does not fetch and it does not hold domain logic.
- Put data fetching in a composable under `dashboard/src/composables/`. Follow the existing composables.
- Keep shared types in `dashboard/src/types/` and keep them in step with the DocType they describe. Avoid `any`.
- Give every component typed props with a named props interface.
- Always handle the loading, empty, error, and disabled states. The user must never reach a dead end.
- Use a toast for short success feedback or a non-actionable background status. Use `backgroundErrorToast` only when the failure happened outside the user's current task.
- Use `reportError` for an API or action failure. It shows one persistent alert at the top center of the viewport. Give it an action-specific title when the automatic error category does not identify the failed task.
- Keep a form or dialog failure inside that form or dialog, before the fields or actions it affects. Put a field validation message directly below its field. Keep a page or list loading failure in its content area.
- Use Frappe UI components and semantic classes for layout, spacing, color, and typography. Use a raw Tailwind class only for what the design system does not cover.
- Do not mix ad hoc Tailwind values with design-system tokens. Inconsistent class usage is a defect.
- Keep line heights and text sizes on the Frappe UI scale.
- Use correct HTML semantics. Give every control a label, a reachable focus state, and keyboard operation.
- Match the pinned Frappe UI version. Report a version mismatch instead of a silent upgrade.

## Documentation

- Write for the reader who must use, change, or operate Central.
- Use ASD-STE100 Simplified Technical English. Use short, direct sentences and one term for one thing.
- Keep each Markdown prose paragraph on one source line. Do not use em dashes.
- Describe current behavior only. Do not describe removed behavior or old interfaces.
- Put detailed behavior in one authoritative location and link to it from summaries.
- Use headings that answer a reader question, such as Purpose, Configuration, Operation, or Validation.
- Use a list or table for more than 3 related items. Give an example when a command, API, or configuration value can be unclear.
- Update the related documentation in the same pull request as a behavior, interface, operation, or layout change.
- Update `CAPABILITIES.md` and the fixtures together when the capability set changes.

## Validation and handover

From `apps/central`, using the Bench Python environment:

```bash
../../env/bin/ruff check central
../../env/bin/ruff format central
python3 scripts/check_patches.py
pre-commit run --all-files
```

From the bench root, using Pilot. Pilot finds the bench from the working directory. Add `-b <bench>` when you run it from elsewhere.

```bash
pilot frappe --site central.localhost run-tests --app central
pilot build --apps central
```

Run a focused module during development and not the entire test suite. If small changes, avoid an entire module and just run the file changes.

```bash
pilot frappe --site central.localhost run-tests --app central --module central.tests.test_<name>
```

Use `pilot frappe ...` for any Frappe CLI command, such as `migrate` or `clear-cache`. Use `pilot` directly for bench-level work, such as `build`, `start`, `restart`, and `install-app`. Run `pilot --help` for the full list.

- Mandatory: review every changed line before you commit.
- Remove complexity that the change introduces or exposes, when the removal stays in task scope.
- Keep valid error handling, boundary validation, cleanup, synchronization, and security checks.
- Validate untrusted input at its boundary. Central is the authorization source, so treat every capability and team check as security-sensitive.
- Run the focused tests for the changed module, and the full app suite before a broad refactor.
- In the handover, report the result, the changed paths, and the verification. Explain implementation details only when the user asks or the reason is not clear.

## Commits and pull requests

### Commits

- Use a short Conventional Commit subject: `type(scope): lower case`.
- Start the subject after the colon in lower case. Do not end it with a period. Capitalize only a proper noun, such as Atlas or MariaDB.
- Use a kebab-case scope and one of `feat`, `fix`, `refactor`, `test`, `docs`, `build`, or `chore`.
- Do not add an AI co-author, session data, or agent data.

### Pull requests

- Use the same Conventional Commit format for the pull request title.
- Keep the description short and use ASD-STE100 Simplified Technical English.
- Follow the validation and handover rules before you write the description.
- State what changed and why it matters. Do not narrate the implementation.
- Group related changes. Include visual evidence only for visual changes.

For a bug fix, use this structure:

```text
## Issue
<One sentence that states the user-visible or operational problem.>

## Summary
<1 or 2 sentences that state the fix and why it matters.>

## What changed
- <Specific change>

## Why
<The technical or business reason for this approach.>

## Screenshots
<Before and after evidence. Omit this section when it does not apply.>

## Related issues
Closes #<issue>
```

For a feature, use this structure:

```text
## Summary
<1 or 2 sentences that state the capability and why it matters.>

## What changed
- <Specific change>

## Why
<The technical or business reason for this approach.>

## Screenshots
<Before and after evidence. Omit this section when it does not apply.>

## Related issues
Refs #<issue>
```

## Agent tooling

Use the most specific available skill for the task. See [agent tooling setup](llm/README.md) for sources and installation commands.

| Skill | Use for |
|---|---|
| `code-style` | Every code edit and code-style question. |
| `quality-code-review` | Frappe correctness, security, performance, concurrency, readability, API design, and test review. |
| `review-like-ankush` | Review of a Frappe diff or pull request. |
| `technical-writing` | Documentation, READMEs, commits, pull requests, and release notes. |
| `ui-design` | Dashboard layout, polish, hierarchy, spacing, typography, color, and accessibility. |
| `grill-me` | Strict review of a plan or design before handover. |
| `diagnose` | A hard bug or a performance regression. |
| `draft-security-advisory` | A security advisory for a fixed vulnerability. |
| `i-have-adhd` | Focused, action-first output. Invoke it by name. |

Do not use `frappe-app-dev` in this repository.
