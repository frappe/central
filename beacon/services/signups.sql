-- title: Signups
-- description: A new customer's trial site is ready within 2 minutes.
-- scope: Global
-- slo_target: 99
-- show_on_status_page: 0
-- sort_order: 9
-- page_on_burn: 0
-- Set Query Region in Beacon to the Central Telemetry Region of Central. Central is in no resource list, so the reporter is the region resource.
-- The time runs from the trial request to the site that answers. A trial site that failed counts as bad. The central-signups rule alerts on the same failures, so a burn does not page.
-- Central counts the sites of the last hour ready within each bucket of 30, 60, 120, 300 and 600 s. Change the target here to another bucket. It needs no Central release.
SELECT {region:String} AS resource_id, toInt64(good) AS good, toInt64(valid) AS valid, last_ts
FROM (
    WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
    SELECT sumIf(value, metric = 'central_signup_ready_within_last_hour' AND labels['le'] = '120') AS good,
           sumIf(value, metric = 'central_signup_steps_last_hour' AND labels['step'] IN ('ready', 'failed')) AS valid,
           any(snapshot) AS last_ts
    FROM datum.samples_recent
    WHERE metric IN ('central_signup_ready_within_last_hour', 'central_signup_steps_last_hour')
      AND resource_id = 'central' AND ts = snapshot
)
WHERE valid > 0
