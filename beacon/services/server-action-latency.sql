-- title: Server action speed
-- description: Customer actions on servers finish within their target time.
-- scope: Global
-- slo_target: 99
-- show_on_status_page: 0
-- sort_order: 8
-- page_on_burn: 0
-- Set Query Region in Beacon to the Central Telemetry Region of Central. Central is in no resource list, so the reporter is the region resource.
-- The time runs from the customer's request to the finished action, so it includes Central's dispatch and is longer than the Atlas host times.
-- Targets: create, start and restart 60 s, stop 30 s, resize 120 s. Only succeeded actions count, because the server-actions service counts the failed ones. Terminate does not count, because no customer waits for it.
-- Central counts the actions of the last hour within each bucket of 30, 60, 120, 300 and 600 s. Change a target here to another bucket. It needs no Central release.
SELECT {region:String} AS resource_id, toInt64(good) AS good, toInt64(valid) AS valid, last_ts
FROM (
    WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
    SELECT sumIf(value, metric = 'central_resource_actions_finished_within_last_hour'
                 AND labels['le'] = multiIf(labels['action'] = 'stop', '30', labels['action'] = 'resize', '120', '60')) AS good,
           sumIf(value, metric = 'central_resource_actions_finished_last_hour' AND labels['status'] = 'Succeeded') AS valid,
           any(snapshot) AS last_ts
    FROM datum.samples_recent
    WHERE metric IN ('central_resource_actions_finished_within_last_hour', 'central_resource_actions_finished_last_hour')
      AND resource_id = 'central' AND ts = snapshot
      AND labels['resource_type'] = 'Server' AND labels['action'] IN ('create', 'start', 'stop', 'restart', 'resize')
)
WHERE valid > 0
