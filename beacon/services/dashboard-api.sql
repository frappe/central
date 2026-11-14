-- title: Dashboard and API
-- description: Requests to the Central dashboard and API succeed.
-- scope: Global
-- slo_target: 99.9
-- show_on_status_page: 1
-- sort_order: 5
-- Set Query Region in Beacon to the Central Telemetry Region of Central. Central is in no resource list, so the reporter is the region resource.
-- Central sends the requests since its last push each minute. The query takes the mean of 5 minutes, so a late or missed push does not make a minute empty. A 5xx is bad. A 4xx is an error of the client, so it is good.
SELECT {region:String} AS resource_id,
       toInt64(round((requests - errors) / 5)) AS good,
       toInt64(round(requests / 5)) AS valid,
       last_ts
FROM (
    SELECT sumIf(value, labels['status_class'] = '5xx') AS errors, sum(value) AS requests, max(ts) AS last_ts
    FROM datum.samples_recent
    WHERE resource_id = 'central' AND metric = 'central_requests' AND ts > now() - INTERVAL 5 MINUTE
)
WHERE requests > 0
