# Rewrite validation

## Purpose

Use these environments to prove the [v0.2 contract](REWRITE_SCOPE.md). Each environment answers a different question. Record the exact Central, Atlas, Pilot, proxy, Cargo, and image revisions used.

## Environments

| Environment | Proves | Does not prove |
|---|---|---|
| A: Contract tests and fakes | Payloads, pagination, state transitions, permissions, scheduling, and recovery logic. | Actual host boot, public routing, or sleep. |
| B: Local Central and Atlas sites | Real token acceptance, tenant enforcement, error envelopes, and persisted migrations. | VM placement without a Metal host. |
| C: Disposable real-region resources | Creation, warm and cold startup, Pilot bootstrap, login, sleep, wake, domains, and supported migration. | Behavior under untested regional scale or failures. |

A unit-test fake must use the pinned public schema. Do not silently copy a moving sibling checkout during CI.

The fake must model uncertain acceptance, delayed observations, partial pages, and failures after a remote side effect. Happy-path payload mocks alone are insufficient.

## Local execution

Run Frappe commands through Pilot from the bench root. Use the selected Pilot environment, not an unrelated executable on the shell path.

```sh
pilot frappe --site central.localhost run-tests --app central --module central.tests.test_team_tenant_id
pilot frappe --site central.localhost run-tests --app central
pilot build --apps central
```

Use the first command after that test module exists on the selected phase branch. See `CLAUDE.md` for lint, format, and pre-commit commands.

A separate source worktree is not automatically installed into a bench. Use a dedicated validation bench or explicitly configure its Central checkout before running tests.

Confirm the database schema matches the tested branch. Do not report tests against an unmigrated schema as proof of code correctness.

Use a disposable test database for migration tests. Do not run broad migration commands on shared staging while reviewing a patch.

## Local regional checks

Configure an Atlas site with a known region ID and Central key-set URL. Publish a Central signing key before asking Atlas to refresh it.

Use Central's actual signer and Atlas's actual verifier. A token decoded only by a Central test does not prove consumer compatibility.

| Case | Expected result |
|---|---|
| Valid Central token and Team tenant header | The request reaches the selected tenant. |
| Missing or invalid tenant header | The request fails with the documented validation response. |
| Wrong audience or issuer | Authentication fails. |
| Tenant A requests Tenant B's VM | The resource remains hidden. |
| Proxy receives an Atlas token | Authentication or claim validation rejects it. |
| New signing key before consumer refresh | Activation policy prevents premature use. |
| Key refresh fails | Existing accepted keys follow the documented cache policy. |

Without a Metal host, test read and validation paths that need no placement. Do not claim that a no-host setup proves VM creation.

## Pilot bootstrap tests

Pilot's `InstanceMetadata` accepts a base URL. `apply_central_config` accepts an injected metadata client. Use those existing seams for local tests.

Do not require a new production environment override only to test credential parsing. A full boot-service test can use a controlled transport or a real guest.

Validate missing fields, invalid endpoints, retry behavior, initial key-set seeding, concurrent application, and bootstrap after a process restart.

Never reuse live credentials in fixtures. Public signing keys can be test data. Private keys and bearer tokens must be disposable test values.

## Populated migration tests

Prepare representative records from the source schema, including several Teams, Regions, resource links, subscriptions, credentials, and pending actions.

Test a partially applied earlier rewrite separately. Preserve known tenant mappings and detect ambiguous mappings before any remote call.

Run the migration twice. Assert record counts, identifiers, references, constraints, and private credential access. Inject an interruption where the migration can resume safely.

Do not use a successful fresh install as a substitute for this test.

## Real-region scenarios

Use an agreed test region, a test Team, and a bounded resource budget. Record every created VM and route for cleanup.

| Scenario | Required evidence |
|---|---|
| Warm signup | Correct prepared shape, metadata bootstrap, automatic route, and successful site login. |
| Cold signup | Progress remains usable and the operation completes without a warm artifact. |
| Idle sleep | Host state confirms sleep while Central synchronization remains active. |
| Wake | Customer traffic restores the site. Record latency and first-request retries. |
| Uncertain create | Recovery finds or resolves the original request without another VM. |
| Worker restart | Pending work resumes from durable records. |
| Delete | VM absence, credential revocation, route cleanup, and required billing effects agree. |
| Resize or migration | The selected public API exposes enough evidence to confirm the requested change. |
| Custom domain | Ownership, route, certificate, renewal, and cleanup succeed. |
| Region outage | Central shows stale state and recovers without inventing deletions. |

VM running state does not prove site readiness. A successful signup must reach the site through its supported public route.

Do not continuously probe the guest during the idle-sleep test. Observe through Atlas or Metal and send customer traffic only for the wake step.

## Release evidence

Each phase PR records its checks and the remaining external gates. Phase 6 records the populated migration rehearsal and real-region results.

Keep secrets out of logs, screenshots, fixtures, PR descriptions, and reports. Record identifiers and redacted error details sufficient for an operator to reproduce failures.
