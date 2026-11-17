# Rubric

## Keep

- Permission denial, cross-team or cross-tenant access, auth, capability checks.
- Money: invoices, payments, credits, refunds, rating, tax.
- State transitions and lifecycle hooks: what happens on insert, update, cancel, delete.
- Retry, replay, idempotency, concurrency, transactions, data patches.
- Boundary contracts with a remote service (request shape, error mapping).
- A regression test for a real bug. The test name, docstring or commit usually says so.
- The only test that covers a line or an outcome.

## Cut

- Its lines are a subset of another test's lines, and that test asserts every outcome this one asserts.
- It tests the framework, not the app: a DocType field exists, a Link field rejects a bad value, `frappe.get_doc` returns a doc, JSON round-trips.
- It tests a constant, a type, or a mapping by repeating it (`assert STATUS["Paid"] == "green"`).
- It only checks that a mock was called with what the code passes it.
- It is a copy of another test with a different literal and no different branch.
- Frontend: a small common component or pure presentation (labels, menus, icons, layout) with no app logic. A type check or an E2E path covers it.

## Merge

- Clones that differ only in literals: one table-driven test with `subTest` (Python) or a loop of cases (node).
- Several tests that each build the same expensive fixture to check one field: one test, several assertions, when they check one behavior.

## Speed up, do not cut

- `time.sleep` in a test: freeze or patch time instead.
- `frappe.db.commit()` in a test: it breaks rollback isolation and slows everything after it. Remove it, or move the data to `setUpClass` with explicit cleanup.
- The same records made in every `setUp`: make them once in `setUpClass`.
- A real network or Atlas or Pilot call: patch the client at the integration boundary.

## Record per candidate

`<test id> | cut, merge into <id>, speed up, keep | reason | evidence (subset of <id>, clone group <n>, <seconds>s)`
