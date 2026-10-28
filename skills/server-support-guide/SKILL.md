---
name: server-support-guide
description: General support guide for customer servers, benches, and sites in Central, for L1, L2, and L4 support staff. Investigates unavailable servers, failed creation, site errors, background jobs, migrations, storage, domains, and TLS. Uses Central records and Pilot evidence to identify the cause, recommend safe Desk or console actions, and escalate when needed. Use first for any support question about a server, bench, or site.
---

# Support a server

Find what is broken, why it is broken, and what action can resolve it.

The reader is support staff, not a developer. Explain the problem in plain words. Name the affected server, site, bench, or task. Give the Desk button or console action when a fix is available.

Do not show code, file paths, shell commands, or raw logs to support staff.

## Rules

- Start with read-only requests.
- Find the affected resource before investigating.
- Use the smallest set of requests needed to identify the problem.
- Match the evidence to the reported incident time.
- Separate observations, likely causes, and confirmed causes.
- Do not assume a cause from a symptom alone.
- Do not treat missing data as evidence of health.
- Do not restart, retry, or resize without evidence that the action can help.
- Do not repeat a failed action without checking why it failed.
- Do not make changes without approval and a read-write session.
- Make one approved change at a time.
- Stop when the evidence is sufficient to give a useful action.
- If the cause is unknown, state what evidence is missing.
- Verify the result after each change.

## Workflow

```text
1. Triage
2. Check the affected resource
3. Identify the cause
4. Explain and recommend an action
5. Fix with approval
6. Verify and report
```

### 1. Triage

Find the server with `read_records` on `Virtual Machine`, or find the site with `read_records` on `Site` and use its `server`.

Identify:

- What is affected: server, bench, site, domain, or task.
- What is broken: unavailable, slow, failed, or intermittent.
- When the problem started.
- Whether the problem is still active.
- Whether one site or multiple sites are affected.

Do not ask for information that Central or Pilot already provides.

If the symptom is slowness, high resource use, or timeouts, use the `performance-inspection` skill.

### 2. Check

Use the symptom table to select the first checks. Do not call every endpoint by default.

| Symptom | Check | Next action |
| --- | --- | --- |
| Server unreachable | `Virtual Machine.status`, Pilot `health` | If stopped, recommend Start. If Running but Pilot is unreachable, check state consistency and host evidence |
| Server creation failed | `Resource Action` with `status` and `error_message` | Identify the failed step and its cause before retrying |
| Site down or 502 | Pilot `sites/<site>`, `sites/<site>/uptime`, `benches/<bench>` | Check site and bench state. Restart only if a process is stuck or stopped and restart is appropriate |
| Old pages or errors after a change | Pilot `logs/<file>` with `search` | Identify cache, asset, migration, or application errors before selecting a fix |
| Background jobs stuck | Pilot `task-worker`, `tasks` with `{"status": "failed"}` | Distinguish failed tasks, stopped workers, and queue delays |
| Update or migration failed | Pilot `migrations/current`, `tasks/<task>/output/content` | Identify the failed patch or step. Retry only when the cause is resolved or retry is safe |
| Disk full | Pilot `storage`, `sites/<site>/storage`, `database/size` | Identify storage consumers and recommend cleanup or expansion |
| Domain or TLS failure | Pilot `sites/<site>/domains` | Check domain state, DNS, and certificate errors. Recommend the matching correction |
| Admin domain error | `Virtual Machine.admin_domain_error` | Identify the failed step before using Retry Admin Domain |
| Site rename failed | `Site.rename_error` | Identify the error before using Retry Site Rename |
| Trial step failed | `Site.trial_error` | Identify the error before using Retry Trial Step |

If the first check does not explain the symptom, expand the investigation.

#### Server unreachable

- A stopped server can be started after approval.
- A Running status does not prove that the guest is healthy.
- Use Sync State when Central and the actual server state may disagree.
- If Pilot is unreachable, do not assume the server is stopped.
- Escalate to Atlas when the evidence indicates a host, storage, or network problem.

#### Site errors

- A 502 can result from a stopped web process, an unhealthy bench, or an upstream connection failure.
- Check bench and site state before recommending a restart.
- For errors after an update, check migration status and relevant logs.
- Clear cache only when stale cache is a supported explanation.
- Do not use repeated restarts to hide an unresolved problem.

#### Background jobs

- A failed task is different from a task waiting in a queue.
- Check worker state, task status, and available queue evidence.
- Start the task worker if it is stopped and should be running.
- Retry a failed task only after checking its error and whether retrying can repeat side effects.
- Do not retry a task that is still running.

#### Migrations

- Identify the failed migration or patch.
- Check whether the failure is temporary or caused by application code, schema state, or missing dependencies.
- Do not retry a migration blindly.
- If the cause requires application changes, refer it to the customer's developer.
- Escalate if the migration state is uncertain or another retry can cause damage.

#### Storage

- Identify what uses the disk before recommending expansion.
- Distinguish database growth, site files, backups, and logs.
- Do not delete customer data or backups.
- Expanding storage can resolve capacity pressure but does not resolve uncontrolled growth.
- Tell the customer what is growing and whether further action is required.

#### Domains and TLS

- Check domain state and available DNS or certificate errors.
- Do not assume that every TLS failure is caused by DNS.
- Tell the customer which DNS record needs correction when evidence supports it.
- Enable or retry TLS only when the required conditions are met.
- Confirm that the domain works after the change.

### 3. Identify the cause

Use evidence from Central, Pilot, and the incident time.

Distinguish:

- **Confirmed:** Direct evidence identifies the failed component or operation.
- **Likely:** Multiple observations support one explanation, but it is not confirmed.
- **Unknown:** The available evidence does not establish a cause.

Do not present a likely cause as confirmed.

If the problem is caused by customer application code, identify the affected app, operation, and error in plain words. Recommend developer investigation.

If the problem appears to be below the guest, use `start_region_investigation` when host-side investigation is justified.

### 4. Explain

Tell support staff:

- What is broken and who is affected.
- What the checks found.
- The confirmed or likely cause.
- What action can resolve it.
- Whether the action has risks or causes downtime.

Example:

"The background task worker stopped at 10:40 UTC. Twelve jobs are waiting. Starting the worker should allow the queue to continue."

Do not show raw logs or code unless the reader explicitly needs technical evidence.

### 5. Fix

The session starts in read-only mode.

Before making a change:

1. Explain the exact action, reason, and expected impact.
2. Ask: "Switch this session to read-write?"
3. Call `switch_to_read_write` only after the user agrees.
4. Request approval for the specific change.
5. Make only the approved change.

| Change | Tool |
| --- | --- |
| Run a Desk action on a record | `run_desk_action` with the document method, such as `retry`, `sync_state`, or `retry_admin_domain` |
| Start, stop, restart, resize, or snapshot a server | `call_central_api`, such as `central.api.servers.restart_server` with `team` and `resource_id` |
| Clear cache, migrate, build assets, restart a bench, retry a task, or start a task worker | `send_pilot_write_request`, such as `POST sites/<site>/actions/clear-cache` |

- Check the action's impact before execution.
- Make one change at a time.
- Do not retry an action merely because it failed.
- Do not make additional changes without approval.
- If the tool reports failure, investigate the failure before continuing.

### 6. Verify and report

Read the same status or monitoring endpoint again.

Confirm that:

- The affected resource is healthy.
- The original symptom has stopped.
- The action did not introduce a new problem.

A successful action response does not prove that the problem is resolved.

If the symptom remains, return to the relevant check. Do not repeat the same fix without new evidence.

Use the `virtual-machine-investigation` report templates when a cause was found.

Report:

- **Impact:** Affected server, bench, site, or task.
- **Time:** Incident time and relevant observations.
- **Evidence:** What Central or Pilot showed.
- **Cause:** Confirmed, likely, or unknown.
- **Action:** What was done or what the user must do.
- **Result:** Resolved, unresolved, or awaiting verification.

Keep the report short. Put the most important finding first.

## Never

- Never terminate, delete, restore, reinstall, or destroy a server, site, bench, backup, or snapshot. If requested, explain the risk and give the Desk steps. The user must perform the action.
- Never install or remove apps on a bench.
- Never edit application code or process configuration.
- Never open a login, console, or credential for the user.
- Never expose passwords, tokens, or other secrets in reports.
- Never perform an unapproved change.
- Never claim that a problem is fixed without verification.

## Escalate

Escalate when:

- The cause cannot be identified with available support tools.
- A fix fails and further attempts have no new supporting evidence.
- A migration fails again or its state is uncertain.
- The action requires application code or configuration changes.
- The evidence points to host, storage, or network infrastructure.
- The required action is outside support permissions.

For host-side problems, use `start_region_investigation` to hand the investigation to Atlas.

Provide the affected resource, incident time, symptoms, checks already completed, and relevant evidence.

Do not escalate without useful context. Do not continue making changes when the risk is unclear.