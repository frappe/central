# Central resource actions failing

Resource Actions create, start, stop, restart, resize and terminate customer servers and sites. The alert key names the region, the resource type and the action.

- `failing:<region>:<type>:<action>` (High): 3 or more actions failed or timed out in 1 hour, and they are 20% of the finished ones.
- `stuck:<region>:<type>:<action>`: the oldest open action waits for 30 minutes (Medium) or 2 hours (High).

1. Open the Resource Action list in Central. Filter by the region, type and action of the alert, and by Failed or Timed Out. Read **Error Code** and **Error Message**.
2. When all failures are in one region, check the Atlas of that region and its Beacon alerts. A host or capacity problem in Atlas fails these actions.
3. For a stuck action, open it and check **Dispatched At** and **Last Checked At**. When nothing checked it recently, the Central workers or the scheduler stopped.
4. Retry an action only when it is safe to repeat. A create that is Uncertain can have made the server already.
