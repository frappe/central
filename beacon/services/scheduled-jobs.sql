-- title: Scheduled jobs
-- description: Central's scheduled jobs run to the end without an error.
-- scope: Global
-- slo_target: 99.9
-- show_on_status_page: 0
-- sort_order: 10
-- page_on_burn: 0
-- Set Query Region in Beacon to the Central Telemetry Region of Central. Central is in no resource list, so the reporter is the region resource.
-- Each run of a scheduled job writes a Scheduled Job Log. Complete is good and Failed is bad. The central-failed-jobs rule alerts on the failures, so a burn does not page.
-- Background jobs that a scheduled job queues do not count here. central-failed-jobs names them.
SELECT {region:String} AS resource_id, toInt64(good) AS good, toInt64(valid) AS valid, last_ts
FROM (
    WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
    SELECT sumIf(value, labels['status'] = 'Complete') AS good,
           sumIf(value, labels['status'] IN ('Complete', 'Failed')) AS valid,
           any(snapshot) AS last_ts
    FROM datum.samples_recent
    WHERE metric = 'central_scheduled_job_runs_last_hour' AND resource_id = 'central' AND ts = snapshot
)
WHERE valid > 0
