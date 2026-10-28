---
name: virtual-machine-investigation
description: Investigates customer server and site failures across Central, Pilot, and Atlas for L1, L2, and L4 support. Finds the first failure, its cause, impact, and responsible layer. Covers unreachable VMs, failed provisioning, Resource Actions, Pilot tasks, site errors, and infrastructure faults. Uses evidence-driven hypotheses, timeline correlation, and structured incident reports. Use for any question asking why a server, bench, site, or operation failed.
---

# Investigate a server problem

Find what failed first, why it failed, what it affected, and what to do next.

Every factual claim must have tool evidence. Separate confirmed facts from hypotheses. Do not invent a cause when evidence is incomplete.

## System layers

```text
Central   VM, Site, Resource Action, Pilot Credential
   |
Pilot     benches, sites, tasks, logs, database
   |
Atlas     VM, Metal host, network, disk
```

Use `read_records` for Central, `send_pilot_read_request` for Pilot, and `start_region_investigation` for Atlas.

Start with Central. Inspect Pilot when reachable. Use Atlas when evidence indicates a problem below Pilot or when VM reachability cannot be explained.

Search the `Central` and `Pilot` knowledge bases when endpoint behavior or system architecture is unclear.

Before writing the final report, load `writing.md` with `load_skill(name="virtual-machine-investigation", file="writing.md")`.

## Rules

- Start with read-only requests.
- Establish the affected resource and incident time first.
- Use the smallest set of requests needed to answer the current question.
- Check timestamps and data freshness before interpreting status.
- Separate observations, hypotheses, and confirmed causes.
- Distinguish the trigger, root cause, propagation, and impact.
- Do not treat correlation as proof of causation.
- Compare with a healthy resource or time window when useful.
- Do not treat missing data as evidence of health.
- Do not escalate to Atlas without relevant evidence or an unresolved VM reachability problem.
- Do not repeat checks that cannot provide new evidence.
- Stop when the cause is sufficiently supported or further investigation is blocked.
- Never make changes without approval and a read-write session.
- Do not expose credentials or secrets.

## Workflow

```text
1. Scope
2. Central records
3. Pilot
4. Form hypotheses
5. Test and narrow
6. Atlas, when indicated
7. Validate conclusion
8. Report
```

### 1. Scope

Find the server with `read_records` on `Virtual Machine`.

Search by name, `title`, `resource_id`, `ipv6_address`, `public_ipv4`, or team.

For a site, read `Site` and follow its `server`.

Identify:

- Affected server, site, bench, or operation.
- Reported symptom and impact.
- First known failure time in UTC.
- Current state: ongoing, recovered, intermittent, or unknown.
- Whether one resource or multiple resources are affected.

Distinguish the reported start time from the first failure observed in records.

If the server cannot be identified, report the missing scope. Do not guess.

### 2. Central records

Read the relevant records for the affected server.

| DocType | Fields |
| --- | --- |
| `Virtual Machine` | `status`, `region`, `atlas_vm_id`, `atlas_host_id`, `state_observed_at`, `last_reported_at`, `admin_domain_error` |
| `Resource Action` | Filter by `server`. Read `action`, `status`, `error_code`, `error_message`, `diagnostic`, `setup_timeline`, `completed_at` |
| `Site` | Filter by `server`. Read `rename_status`, `rename_error`, `trial_state`, `trial_error` |
| `Pilot Credential` | Filter by `server`. Read `status`, `last_used_at` |
| `Region` | `reachable`, `connection_error`, `connection_checked_at` |

Interpret timestamps carefully:

- An old `state_observed_at` means the recorded VM state may be stale.
- An old `last_reported_at` indicates a gap in the corresponding reporting activity.
- An old `last_used_at` indicates no recent recorded credential use. It does not prove Pilot stopped.
- An old `connection_checked_at` means the region's current reachability is not established.

For failed operations, use the Resource Action timeline to find the first failed step.

Do not assume the last error is the root cause. It may be a consequence of an earlier failure.

### 3. Pilot

Call `send_pilot_read_request` with `health` first.

If it fails:

1. Check the VM status and freshness in Central.
2. Check the region's reachability and observation time.
3. Check whether a Resource Action explains the state.
4. Use Atlas when VM or infrastructure evidence is needed.

A failed Pilot health request proves only that the request did not succeed. It does not by itself prove that the VM is down.

If Pilot is reachable, read only the endpoints relevant to the symptom.

| Symptom | Pilot paths |
| --- | --- |
| Site down or slow | `sites/<site>`, `sites/<site>/monitoring`, `sites/<site>/uptime`, `monitor/status` |
| Site errors | `logs`, then `logs/<file>` with `search` |
| Tracebacks | `logs/<file>` with `{"search": "Traceback", "lines": 500}` |
| Failed task | `tasks` with `{"status": "failed"}`, `tasks/<task>`, `tasks/<task>/output/content`, `task-worker` |
| Database slow or locked | `database/processlist`, `database/lockwaits`, `database/diagnostics`, `database/history` |
| Disk or memory | `system`, `metrics`, `storage`, `sites/<site>/storage`, `database/size` |
| Domain or TLS | `sites/<site>/domains` |
| Update or migration | `migrations/current`, `migrations`, `benches/<bench>` |

Use `audit-events` to identify recorded Pilot actions and their times.

For endpoint parameters, search the `Pilot` knowledge base for `docs/admin-api-reference.md`.

For sustained slowness or resource pressure, use `performance-inspection` rather than duplicating its detailed checks.

Do not read every endpoint by default.

### 4. Form hypotheses

If the cause is already proven, investigate its mechanism and impact. Do not invent alternative explanations.

Otherwise, form a small set of plausible hypotheses.

For each hypothesis, identify:

- **Mechanism:** How it could produce the symptom.
- **Supporting evidence:** What observations agree with it.
- **Expected evidence:** What should be present if it is true.
- **Contradiction:** What observation would rule it out.

Prefer hypotheses from different layers when the evidence does not identify the responsible layer.

Do not present a hypothesis as a finding.

### 5. Test and narrow

Select the check that can eliminate the most plausible explanations with the least work.

- Use the smallest read that answers one question.
- Check whether the suspected event occurred before the symptom.
- Compare affected and unaffected resources when useful.
- Compare incident metrics with a healthy time window.
- Check whether the mechanism explains the complete impact.
- Reconsider a hypothesis when evidence contradicts it.

Keep these concepts separate:

| Concept | Meaning |
| --- | --- |
| Trigger | Event that started the failure sequence |
| Root cause | Underlying condition that made the failure possible |
| First failure | Earliest observed failed operation or component |
| Propagation | How the failure affected other components |
| Impact | What the customer experienced |

The first observed failure is not necessarily the root cause.

A task near the incident time does not prove that the task caused the incident.

Stop testing when evidence is sufficient for a supported conclusion or when further checks cannot resolve the uncertainty.

### 6. Atlas

Use Atlas when the evidence points below Pilot or VM reachability remains unexplained.

Examples:

- Pilot health fails while Central reports a Running VM, and Central state or connectivity checks cannot explain the failure.
- A VM stopped, restarted, or froze without an explanatory Pilot task or Resource Action.
- Logs show disk I/O errors, a read-only filesystem, or kernel errors.
- Metrics show CPU steal, unexplained storage latency, or VM resource throttling.
- Evidence indicates network loss to or from the VM.
- Multiple affected VMs suggest a shared host or regional problem.

Do not escalate merely because guest CPU use is low or a single Pilot request failed.

Call `start_region_investigation` with:

- `region`: The server's region.
- `problem`: Symptom, impact, and incident start time.
- `context`: `atlas_vm_id`, `atlas_host_id`, server name, and relevant evidence.

Use `get_region_investigation` to check progress until the investigation completes, fails, or cannot make further progress.

Do not poll indefinitely.

Use the Atlas report as evidence. Include its investigation ID.

If Atlas is unavailable, report the blocked investigation and the missing evidence.

### 7. Validate conclusion

Challenge the conclusion before reporting.

Check that:

- The proposed cause explains the observed symptoms.
- The cause is consistent with the incident timeline.
- The scope matches the affected resources.
- The mechanism has supporting evidence.
- Important contradictions have been addressed.
- The responsible layer is supported by evidence.

Classify the outcome:

| Outcome | Requirement | Confidence |
| --- | --- | --- |
| Confirmed cause | Direct evidence shows the mechanism, timing and scope agree, and no important contradiction remains | High |
| Probable cause | Independent observations support the mechanism, but direct proof is unavailable | Medium |
| Blocked | Required evidence, access, or investigation results are unavailable | Low |
| No fault found | Relevant checks cover the reported incident window and show no fault | Based on coverage |

Do not assign high confidence to "No fault found" when historical data is missing or the incident window was not covered.

If evidence supports only the first failure, report that failure without claiming to know its root cause.

### 8. Report

Before reporting, load `writing.md` with `load_skill(name="virtual-machine-investigation", file="writing.md")`.

Write in ASD-STE100 Simplified Technical English.

Write only the report. Do not include a preamble, repeated question, internal reasoning, or raw tool output.

- Put the most important finding first.
- Use bullets by default.
- Use tables for multiple resources with the same fields.
- Use ASCII diagrams only when a cause chain helps.
- Omit empty sections.
- Preserve server names, site names, and relevant IP addresses.
- Never print credentials or secrets.
- Identify evidence sources and their time ranges.

#### Incident found

```markdown
**<Layer> <component>: <failure>, since <YYYY-MM-DD HH:MM UTC>**

- Status: <ongoing | recovered | intermittent | unknown>
- Impact: <affected server, sites, team>
- Cause: <confirmed or probable mechanism>
- Confidence: <high | medium | low>, <reason>
- Containment: <action to stop ongoing damage, if needed>

```text
[trigger] --> [first failure] --> [propagation] --> [impact]
```

| Resource | State | Measure | Since (UTC) |
| --- | --- | --- | --- |
| <name> | <state> | <value> | <MM-DD HH:MM> |

| Time (UTC) | Source | Event |
| --- | --- | --- |
| <MM-DD HH:MM> | <record, Pilot path, or Atlas investigation> | <event> |

**Evidence**
- <source and time range>: <measured observation>

**Ruled out**
- <hypothesis>: <contradicting evidence>

**Unexplained**
- <missing evidence or unresolved observation>

**Next**
1. [read] <check needed to resolve uncertainty>
2. [change] <owner>: <supported corrective action>
```

#### No fault found

```markdown
- Status: No fault found in the checked period.
- Scope: <resources and time window>
- Evidence: <checks and measurements>
- Limit: <coverage limitation, if any>
```

#### Blocked

```markdown
- Status: Cause not confirmed.
- Known: <verified observations>
- Missing: <required evidence or access>
- Next: [read] <check needed to continue>
```

## Changes

The investigation is read-only.

Mark actions that change state with `[change]`. Identify who performs each action:

- Support operator in Desk.
- Customer.
- Customer's developer.
- Atlas engineer.

If damage is ongoing, recommend safe containment before a permanent fix.

To make an approved change, follow the Fix workflow in `server-support-guide`:

1. Explain the action and its impact.
2. Ask to switch the session to read-write.
3. Obtain approval for the specific change.
4. Execute only that change.
5. Verify the result.

Never terminate or destroy a resource.

## Progress updates

During a long investigation, give brief updates when meaningful evidence becomes available.

State:

- What is confirmed.
- What remains unknown.
- What will be checked next.

Do not repeat the same progress update. Do not present an untested hypothesis as fact.