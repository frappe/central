# Central background work stuck

Central does work that customers wait for, but that no request shows. The alert key names the check.

| Alert key | Check |
| --- | --- |
| `billing-run-open-seconds` | Open the Billing Run list. The newest run is not Complete after 1 day. Read **By Status**. |
| `route-pending-seconds:<type>`, `routes-failed-in-1h:<type>` | Open the Site Domain list. Filter by Pending or Failed. Check the proxy of the region. |
| `automatic-snapshots-failed-today`, `snapshot-pending-seconds` | Open the VM Snapshot list. Read **Error Detail**. Check the Atlas of the region. |
| `emails-failed-in-1h`, `email-waiting-seconds` | Open the Email Queue list. Read the error. Check the outgoing Email Account. |
| `job-late-seconds:<job>` | The scheduler or the workers stopped. Run `bench --site <site> doctor`. |
| `queued-jobs:<queue>`, `jobs-failed-in-1h:<queue>` | Open RQ Job in Desk. Read the failed jobs. Add workers when the queue only grows. |
| `invoice-sync` (Low) | Open the Invoice list. Filter **ERPNext Sync Status** = Failed. Read **ERPNext Sync Error**. |
