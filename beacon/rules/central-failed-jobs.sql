-- title: Central jobs failing
-- description: Background or scheduled jobs in Central keep failing. Provisioning, billing or syncs are late.
-- severity: Medium
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-failed-jobs.md
-- charts: central-jobs, central-job-queue
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- 3 background jobs that failed in one queue in 1 h is a job that keeps failing, not one bad run. A scheduled job that failed 2 times in 1 h fails on each run.
-- affected names the failed methods of the queue, from central_jobs_failed_last_hour.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, a.alert_key AS alert_key, a.value AS value, a.detail AS detail, f.affected AS affected
FROM (
    SELECT concat('queue:', queue) AS alert_key, failed AS value,
           concat(toString(failed), ' background jobs failed in the ', queue, ' queue in 1 h (limit 3)') AS detail
    FROM (
        SELECT labels['queue'] AS queue, sum(value) AS failed
        FROM datum.samples_recent
        WHERE metric = 'central_jobs_failed_last_hour' AND resource_id = 'central' AND ts = snapshot
        GROUP BY queue
    )
    WHERE failed >= 3
    UNION ALL
    SELECT concat('scheduled:', labels['job']), value, concat('the scheduled job ', labels['job'], ' failed ', toString(value), ' times in 1 h (limit 2)')
    FROM datum.samples_recent
    WHERE metric = 'central_scheduled_job_runs_last_hour' AND resource_id = 'central' AND ts = snapshot
      AND labels['status'] = 'Failed' AND value >= 2
) AS a
LEFT JOIN (
    SELECT concat('queue:', labels['queue']) AS alert_key,
           mapFromArrays(groupArray(20)(labels['method']), groupArray(20)(concat(toString(value), ' failed in 1 h'))) AS affected
    FROM datum.samples_recent
    WHERE metric = 'central_jobs_failed_last_hour' AND resource_id = 'central' AND ts = snapshot
    GROUP BY alert_key
) AS f ON f.alert_key = a.alert_key
