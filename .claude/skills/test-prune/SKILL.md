---
name: test-prune
description: Find and remove redundant tests with measurements, and make a slow suite fast without losing what it protects. Use when you add, change or remove a test file or test case (check the new test against the rubric only; do not run the full measurement), or when a user says tests are redundant, slow, bloated, agent-generated or over-tested, asks to cut or refactor a test suite, wants CI faster, or asks whether small components need tests. Built for Frappe apps (run-tests, IntegrationTestCase) and node --test / Playwright frontends; the method works for any Python suite.
---

# Test prune

Keep a test unless a measurement and the rubric both say it can go.

## Rules

- Never cut a test only because a script flagged it. Scripts find candidates. `references/rubric.md` decides.
- Never cut a protected test: permission denial, cross-team or cross-tenant, auth, money, state transition, retry or idempotency, data loss, or a regression test for a real bug. `redundant.py` marks names that look protected; read the body too.
- A coverage subset is not proof alone. Test A can cover the same lines as B and still assert something B does not. Before you cut A, check that B (or the test you merge into) asserts every outcome A asserts.
- Measure on a disposable test site (`allow_tests: true`). Never on a real or shared site.
- Every cut keeps the full suite green and keeps every CI workflow and PR check green. Run the suite after each batch, not once at the end.
- Make the run faster before you delete tests. Check first whether the suite can run in parallel CI jobs.

## When you add or change a test

Do not run the measurement. Check only the tests in your diff:

1. Read `references/rubric.md`. The test must protect a behavior from the Keep list, or the only path to a line or outcome.
2. Search the module's tests for one that already asserts the same outcome. If one exists, extend it or skip the new test.
3. A case that differs from an existing test only in its values goes into that test as a `subTest` case.
4. No `time.sleep`, no `frappe.db.commit()`, and no records made in `setUp` that `setUpClass` can make once.
5. Frontend: test a hot path or the app's own non-trivial logic, not a small common component.

## Workflow for a suite

1. **Inventory.** Count tests per suite and read CI: which job runs which suite, and how long each step takes (`gh run view <id> --json jobs`). Write down the baseline: test count, wall time, CI time.
2. **Measure.** Start the bench services, then migrate the test site and check the output says it migrated: without services, `migrate` prints a warning and exits 0, and the stale schema makes tests fail for no code reason. Run `scripts/measure.sh <site> <app> <app-source-dir> <out-dir> [exclude-regex]`. It runs each test module in its own coverage process with one context per test and branch coverage (line coverage alone matches tests that take opposite branches), because one long process loses the per-test context for many classes. It writes `modules.tsv` (wall seconds and result per module, setup included) and the runner log that stamps when each test class starts. Expect 2 to 3 times the normal run time. A module that fails here but passes in the full run depends on state that earlier modules leave behind. It can fail in a CI job that runs it first, so fix the test or the site before you split CI.
3. **Rank.**
   - `python3 scripts/slow.py <out-dir>/frappe.testing.log` lists the slowest test classes and modules, setUpClass included. Slow classes are where a cut or a fix (shared fixture, no sleep, no commit) pays.
   - `python3 scripts/redundant.py <out-dir>/.coverage` lists, per test file, tests whose covered lines are a subset of another test's lines, and the smallest set of tests that keeps every covered line (greedy set cover).
   - `python3 scripts/clones.py <tests-dir>` groups tests with the same body shape after literals are removed. Merge a group into one table-driven test (`subTest` loop).
4. **Judge.** Walk each candidate with `references/rubric.md`. Record a verdict: cut, merge into `<test>`, speed up, or keep with the reason.
5. **Frontend.** Keep tests for hot paths (signup, sign-in, checkout, server or site creation, auth redirect) and for the app's own non-trivial logic. Cut tests of small common components and pure presentation. A type check or an E2E test that already walks the path covers them.
6. **Cut in batches.** One module or area per batch. After each batch: run the touched modules, then the full suite. Re-measure the module and run `python3 scripts/gate.py <before .coverage> <after .coverage> <test module>`. It fails and lists the lines when the module's tests cover fewer source lines than before.
7. **Speed up CI.** Use at most 2 CI jobs, grouped by module (for example billing and core), not by test count. Run each group in one process: `run-tests --module` takes one module, so use a small script that calls `frappe.commands.testing.main` with the group's module list; one process per module repeats the Frappe start-up for every module. Skip a group on a pull request only when every changed file is code its tests never run, measured from the coverage data, and run every group on a push to the base branch. Do not switch to `run-parallel-tests` without proof: it loads each file with plain `unittest`, skips setup `run-tests` does, and exits 0 on failure unless `CI` is set. Keep every job name a required check uses, for example with a gate job that has the old name and `needs` the matrix.
8. **Report.** Before and after: test count, local wall time, CI time, coverage percent. List what you cut by category, and what you did not measure.

## References

- `references/rubric.md`: keep, cut, merge and speed-up rules.
- `scripts/measure.sh`, `scripts/slow.py`, `scripts/redundant.py`, `scripts/clones.py`, `scripts/gate.py`. `scripts/test_scripts.py` checks their logic.
