# Greptile Review Rules

## How to review

Review the change in context of the PR. Every rule below applies to lines this pull request adds or rewrites.

- Do not flag pre-existing code that the change only moves, reindents, renames, or happens to sit next to.
- Do not comment when the code is correct. A rule is a reason to look, not a quota to fill.
- Comment once per issue. Do not repeat the same finding on every occurrence. Say "same at lines X, Y" instead.
- State the problem and the concrete fix in 1 or 2 sentences. Do not ask the author to explain a change that the diff already explains.
- Skip a finding when you are not confident the code is wrong. A wrong comment costs more than a missed nit.
- Do not restate what the change does, and do not praise it.
- Judge a rule by its intent. When a rule does not fit the situation, stay silent rather than apply it literally.

Central is in active development and is not deployed to production. Do not ask for backward compatibility, migration shims, deprecated aliases, or rolling-upgrade safety unless the change is about data that already exists.

## Mandatory

- [Mandatory] When a test changes alongside a bug fix, flag a test that was weakened or rewritten to match the new behavior instead of the behavior being fixed to satisfy the test's original intent.
- [Mandatory] Flag a behavior change that ships with no added or updated test. A pure refactor, rename, move, or formatting change needs no new test.
- [Mandatory] Flag a change that makes an existing document in this repository wrong. Do not ask for new documentation that the repository does not already keep.
- [Mandatory] Flag a change to `fixtures/capability.json` or `fixtures/team_role.json` that does not update `CAPABILITIES.md`.
- [Mandatory] Flag a function this change adds or rewrites with cyclomatic complexity above 8.
- [Mandatory] Flag an added comment that explains what changed or why the change was made. That belongs in the commit message or the pull request description.
- [Mandatory] Flag a new explanatory comment block at the top of a file. Allow license headers and a short module docstring.
- [Mandatory] Flag an added comment or document paragraph that does not use ASD-STE100 Simplified Technical English, contains an em dash, or is hard-wrapped mid-paragraph. Allow tables, examples, and code blocks.
- Flag an added comment that restates the code next to it.
- Flag a committed plan file such as `plan_*.md`.

## Commits and pull requests

- Flag a commit subject that does not match `type(kebab-case-scope): lower case`, where type is one of `feat`, `fix`, `refactor`, `test`, `docs`, `build`, or `chore`.
- Flag a commit subject that starts in upper case after the colon, ends with a period, or runs past about 72 characters. A proper noun may be capitalized.
- Flag a pull request description that does not state what changed and why, or that narrates the implementation instead.
- Flag a bug-fix description that does not state the issue before the fix.
- Flag an AI co-author trailer, session data, or agent metadata in a commit or a pull request.

## Boundaries

- Flag an outbound call to Atlas, Pilot, or Cargo made outside `central/integrations/`.
- Flag a write to the `Asset` or `Site` mirror from outside the integration layer. Mirror upserts belong in `central/mirror.py`.
- Flag token minting or verification added outside `central/sso.py`.
- Flag domain logic added to a `central/api/` route or a `hooks.py` entry. Those layers parse input, authorize, delegate, and return.
- Flag a Team Member, Team Role, or Role Capability row read directly in a controller, an API route, a page, or a service. Those reads belong in `central/iam.py`.

## Permissions

Central scopes access by Team capability. A user holds a role in a Team, the role carries capabilities, and a document is reachable through its `team` field.

- Flag a DocType that gains a `permission_query_conditions` entry without a matching `has_permission` entry, or the reverse. Both are needed. One alone leaks either the list or the single document.
- Flag a hand-written permission pair for a DocType with a `team` field where `_team_field_query_conditions` and `_team_field_has_permission` already apply.
- Flag a query condition that returns an empty string or no filter when the user has no qualifying team. It must return `1 = 0`.
- Flag a list scoped by team membership where the capability set is what should scope it. Two members of one Team can differ on a capability.
- Flag `ignore_permissions=True` added without one comment line above it that states why.
- Flag a new capability string used at a call site that is absent from `CAPABILITIES.md` and the fixtures.
- Flag a new or changed permission rule with no test in `central/tests/`, including the denial case.
- Flag a whitelisted API method without type annotations.
- Flag `frappe.get_all` in a read that runs on behalf of a signed-in user and returns team-owned records, where `frappe.get_list` would apply the query conditions. This rule does not apply to `central/iam.py`, `central/permissions.py`, a patch, a scheduled task, a background job, the integration layer, demo or developer setup, or a test. Those run as the system, and the permission layer itself must not call back into permissions.
- Flag a new DocType that stores per-team records and has no indexed `team` link field. Do not apply this to a Single, a system or catalog DocType such as Capability or Region, or a child table scoped through its parent.

## Python

- Flag behavior placed outside the module, controller, service, or task that owns it.
- Flag a new public function or important data structure without type hints.
- Flag a broad or generic exception where a specific one applies, and broad error handling that hides partial or corrupt state.
- Flag a user-facing string that is not wrapped in `_()`.
- Flag a resource or server action that fails without the error envelope in `central/errors.py`. An internal guard or a validation `frappe.throw` does not need the envelope.
- Flag raw SQL where `frappe.db` or `frappe.qb` is sufficient.
- Flag a read that joins more than 2 tables without `frappe.qb`, and a query issued once per row of a loop. A `frappe.get_cached_value` or `get_cached_doc` lookup in a loop is acceptable.
- Flag an index or unique constraint added in a patch. It belongs in the controller's `on_doctype_update`.
- Flag a change to existing data or a field rename that needs a patch in `central/patches/` and does not add one. A new nullable field needs no patch.
- Flag custom machinery where a standard Frappe API, an existing repository helper, or a built-in DocType is sufficient.
- Flag mutable global state, circular imports, and a lazy re-export in a package `__init__.py`.
- Flag state with more than one owner, and temporary state that leaks outside its object or module.
- Flag a retry around an operation that is not safe to repeat.
- Flag clever code where clear code is practical, and implicit configuration where explicit configuration is practical.
- Flag real duplication or coupling that DRY, SOLID, or KISS would remove. Also flag an abstraction layer added in their name with only one caller and no second use in sight.
- Flag a function this change adds or rewrites that runs well past 25 lines and splits cleanly without harming readability.
- Flag a file this change creates, or grows past 500 lines, that should be split or grouped.
- Flag a new generic `utils`, `helpers`, `common`, or `misc` folder, a new same-prefix module where a folder belongs, and an unnecessary abbreviation in a new name.
- Flag a new no-argument method that returns one noun-like value and is not a `@property`, and a new property that takes arguments or does multi-step work where `get_<noun>()` is clearer.
- Flag a new private method that is private only because it has one caller.
- Flag a new boolean property or method without an `is_` or `has_` prefix.

## Desk and operations

Desk is the operator surface. Apply this section to a new DocType, and to an existing DocType when the change adds a field or a state that belongs in these places. Do not audit an untouched DocType.

- Flag a new DocType whose identity, owning team, state, and key number or timestamp are not marked `in_list_view`.
- Flag a new status, team, region, cluster, or type field that is not marked `in_standard_filter`.
- Flag a field the list filters or sorts on that has no index.
- Flag a new DocType with no `title_field` or `search_fields` where the record is named by a hash or a generated id. A DocType named by a readable field needs neither.
- Flag a new status or state field with no indicator colour mapping.
- Flag a new DocType with more than about 15 fields laid out as one flat column, with no tabs or sections.
- Flag a new credential, token, raw payload, or debug field that is not in a collapsed section or a separate tab.
- Flag a new field written only by the system or mirrored from Atlas that is not read-only.
- Flag a new Link field pointing at a DocType whose `links` array does not offer the reverse connection, when an operator would follow it.
- Flag a new field that stores a related record as plain text where a Link field applies.
- Flag a new whitelisted method that an operator would trigger by hand, such as retry, resend, reconcile, rotate, or cancel, that has no desk Action button in the same change.
- Flag a desk Action button that is shown regardless of document state or user permission, that performs a destructive action without confirmation, or that holds logic instead of calling the server method that owns it.
- Flag an added `except` block in a background job or a scheduled task that swallows the failure without recording a readable error on the record it was working on.

## Dashboard

- Flag a new component that hand-builds something Frappe UI already provides.
- Flag a raw Tailwind class used for layout, spacing, color, or typography that the design system already covers, and a text size or line height off the Frappe UI scale.
- Flag a new component placed by name prefix instead of in the common, layout, or feature folder that owns it.
- Flag a table action, confirmation dialog, empty state, or mutation runner duplicated from one that already exists.
- Flag data fetching or domain logic added to a page where it belongs in a composable.
- Flag a new component without typed props, and `any` where a concrete type is practical.
- Flag a view that fetches data and does not handle its loading, empty, and error states, and a control that stays enabled while its action is in flight. A purely presentational component needs none of these.
- Flag a new interactive control with no accessible label, no visible focus state, or no keyboard operation, and a `div` used where a semantic element applies.
- Flag a DocType change that leaves the matching type in `dashboard/src/types/` stale, when both are visible in this change.
- Flag a Frappe UI version bump that the description does not mention.

## Tests

- Flag a new test that asserts nothing meaningful, or that exists only to raise coverage.
- Flag a test name that does not say what behavior it checks.
- Flag a test that depends on execution order, wall-clock time, or another test's data.
- Flag a test comment that restates the test code.
