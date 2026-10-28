---
name: virtual-machine-investigation
description: Investigates a problem with a customer server in Central, such as a Virtual Machine that is down, slow, or unreachable, a failed provisioning or Resource Action, a failed Pilot task, or a site that is down, slow, or shows errors. Uses Central records, the server's Pilot Admin API, and the region's Atlas investigator to find the first failure and its owner. Use for any "why is this server or site broken" question.
---

# Investigate a server problem

Find what failed first, why it failed, what it affected, and what to do next. Every factual claim needs tool evidence.

A server has 3 layers. Find the layer that failed first:

```text
Central   Virtual Machine, Site, Resource Action, Pilot Credential   (records: read_records)
   |
Pilot     benches, sites, tasks, logs, database inside the VM       (read_pilot_api)
   |
Atlas     the VM, its Metal host, network, and disk in the region    (start_region_investigation)
```

Read Central records first. Then read Pilot. Hand a problem to Atlas only when the evidence points below Pilot.

Search the `Central` knowledge base for how Central works, and the `Pilot` knowledge base for how Pilot works. Before the report, read `writing.md` with `load_skill(name="virtual-machine-investigation", file="writing.md")`.

## Workflow

Copy this checklist into your notes and follow it:

```text
- [ ] 1 Scope
- [ ] 2 Central records
- [ ] 3 Pilot
- [ ] 4 Hypotheses
- [ ] 5 Test and narrow
- [ ] 6 Atlas, only for host-side evidence
- [ ] 7 Report
```

### 1. Scope

Find the server with `read_records` on `Virtual Machine`. Search by name, `title`, `resource_id`, `ipv6_address`, `public_ipv4`, or team. For a site name, read `Site` and follow its `server`.

Find the symptom, the affected server and sites, the first failure time in UTC, and the current state: ongoing, recovered, intermittent, or unknown.

If you cannot identify the server, report that. Do not invent a scope.

### 2. Central records

Read these for the server:

| DocType | Fields that matter |
| --- | --- |
| `Virtual Machine` | `status`, `region`, `atlas_vm_id`, `atlas_host_id`, `state_observed_at`, `last_reported_at`, `admin_domain_error` |
| `Resource Action` | Filter on `server`. `action`, `status`, `error_code`, `error_message`, `diagnostic`, `setup_timeline`, `completed_at` |
| `Site` | Filter on `server`. `rename_status`, `rename_error`, `trial_state`, `trial_error` |
| `Pilot Credential` | Filter on `server`. `status`, `last_used_at` |
| `Region` | `reachable`, `connection_error`, `connection_checked_at` |

An old `state_observed_at` means Central does not know the current state. An old `last_used_at` means Pilot stopped calling Central.

### 3. Pilot

Call `read_pilot_api` with `health` first. If it fails to connect, Pilot or the VM is unreachable: go to step 6.

Then read only what the symptom needs:

| Symptom | Paths |
| --- | --- |
| Site down or slow | `sites/<site>`, `sites/<site>/monitoring`, `sites/<site>/uptime`, `monitor/status`, `logs` then `logs/<file>` with `search` |
| Errors in a site | `logs/<file>` with `{"search": "Traceback", "lines": 500}` |
| Failed operation | `tasks` with `{"status": "failed"}`, `tasks/<task>`, `tasks/<task>/output/content`, `task-worker` |
| Database slow or locked | `database/processlist`, `database/lockwaits`, `database/diagnostics`, `database/history` |
| Disk or memory | `system`, `metrics`, `storage`, `sites/<site>/storage`, `database/size` |
| Domain or TLS | `sites/<site>/domains` |
| Update or migration | `migrations/current`, `migrations`, `benches/<bench>` |

`audit-events` shows who did what in Pilot, and when. For the query parameters of a path, search the `Pilot` knowledge base for `docs/admin-api-reference.md`.

Missing data is not evidence of health.

### 4. Hypotheses

When the cause is uncertain, form 2 to 4 plausible hypotheses in different layers. For each one, identify the mechanism, the evidence expected if it is true, and one observation that would prove it false.

If a failure is already proven, investigate its cause instead of inventing alternatives.

### 5. Test and narrow

Run the test that can rule out the most competing explanations first. Use the smallest read that answers one question. Compare with a healthy site on the same bench, or a normal time window.

Correlation is not causation. A task near a failure does not prove that the task caused the failure.

Keep these separate: the trigger, the root cause, the propagation, and the impact.

### 6. Atlas

Hand the problem to Atlas only when the evidence points below Pilot:

- Pilot `health` cannot connect, but the Virtual Machine `status` is Running.
- The VM restarted, stopped, or froze without a Pilot task or a Resource Action that explains it.
- Logs show disk I/O errors, a read-only file system, or kernel errors.
- `system` or `metrics` shows high CPU steal, or slow disk with a low load in the VM.
- Network loss to the VM or from the VM.

Call `start_region_investigation` with the `region`, a problem that names the symptom and the start time, and a context with `atlas_vm_id`, `atlas_host_id`, the server name, and your evidence. Poll `get_region_investigation` until the status is completed or failed. Use its report as evidence, and name the investigation ID.

### 7. Challenge the conclusion

Check that the cause explains the symptoms, agrees with the timeline, has supporting evidence, and belongs to the named layer.

| Outcome | Condition | Confidence |
| --- | --- | --- |
| Confirmed cause | Direct evidence shows the mechanism. Timing and scope agree. No important contradiction. | High |
| Probable cause | Independent observations support it. Alternatives are weaker. Direct proof is unavailable. | Medium |
| Blocked | Necessary records, Pilot access, or Atlas evidence is unavailable. | Low |
| No fault found | Checks are healthy in the window, with sufficient coverage. | High |

## Changes

You are read-only. Mark a recommendation that changes state with `[change]`, and say who does it: the operator in Desk, the customer, or an Atlas engineer. If damage continues, recommend safe containment first.

## Report

Write in ASD-STE100 Simplified Technical English, as `writing.md` describes. Write only the report. No preamble, repeated question, internal reasoning, or raw tool output.

Use bullets by default. Use tables for 2 or more resources with the same fields. Use an ASCII diagram only for the cause chain, in a `text` code block. Use plain ASCII characters inside that diagram.

Omit empty sections. Keep server names, site names, and IP addresses. Never print credentials.

### Incident found

````markdown
**<Layer> <component>: <failure>, since <YYYY-MM-DD HH:MM UTC>**

- Status: <ongoing | recovered | intermittent | unknown>
- Impact: <server, sites, team>
- Cause: <confirmed or probable mechanism>
- Confidence: <high | medium | low>, <reason>
- Containment: <action that stops damage, if ongoing>

```text
[<trigger>] --> [<first failure>] --> [<propagation>] --> [<impact>]
```

| Resource | State | Measure | Since (UTC) |
| --- | --- | --- | --- |
| <name> | <state> | <value> | <MM-DD HH:MM> |

| Time (UTC) | Source | Event |
| --- | --- | --- |
| <MM-DD HH:MM> | <record, Pilot path, or Atlas investigation> | <event> |

**Evidence**
- <record or Pilot path>, <time range>: <observation>

**Ruled out**
- <hypothesis>: <evidence against it>

**Unexplained**
- <observation or missing evidence>

**Next**
1. [read] <check needed to confirm the cause>
2. [change] <who>: <supported corrective action>
````

### No fault found

```markdown
- OK: <resources and time window checked>. No fault found.
- Evidence: <supporting measurement, if useful>
```

### Blocked

```markdown
- Status: Cause not confirmed.
- Known: <verified observations>
- Missing: <required records, access, or evidence>
- Next: [read] <check that can resolve the uncertainty>
```

## Progress updates

Before the final report, give short updates with what is confirmed, what is unknown, and what you will check next. Never present an untested hypothesis as a fact.
