-- title: Server actions
-- description: Customer actions on servers and sites finish without an error.
-- scope: Global
-- slo_target: 99
-- show_on_status_page: 1
-- sort_order: 6
-- page_on_burn: 0
-- Set Query Region in Beacon to the Central Telemetry Region of Central. Central is in no resource list, so the reporter is the region resource.
-- The create, start, stop, restart and resize actions count. Terminate does not, because no customer waits for it. Failed and Timed Out are bad.
-- Each collection counts the actions that finished in the last hour, so each action counts in 60 minutes and the ratio stays correct. A burn does not page, because the central-resource-actions rule pages on the same failures.
SELECT {region:String} AS resource_id, toInt64(succeeded) AS good, toInt64(finished) AS valid, last_ts
FROM (
    WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
    SELECT sumIf(value, labels['status'] = 'Succeeded') AS succeeded, sum(value) AS finished, any(snapshot) AS last_ts
    FROM datum.samples_recent
    WHERE metric = 'central_resource_actions_finished_last_hour' AND resource_id = 'central' AND ts = snapshot
      AND labels['action'] != 'terminate'
)
WHERE finished > 0
