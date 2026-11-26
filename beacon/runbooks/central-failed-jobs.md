# Central jobs failing

The alert key names the problem.

- `queue:<queue>`: 3 or more background jobs failed in the queue in the last hour. The alert names the methods and their counts.
- `scheduled:<job>`: the scheduled job failed 2 or more times in the last hour.

1. Open the RQ Job list in Central desk and filter by Status failed and the queue. Open a job to read its traceback.
2. For a scheduled job, open the Scheduled Job Log list and filter by the job and Status Failed. Its Error Log has the traceback.
3. When many methods fail at the same time, look in the Error Log for a shared cause, such as a database or Redis error.
4. A scheduled job runs again on its next schedule. Queue a failed background job again only when its method is safe to repeat.
