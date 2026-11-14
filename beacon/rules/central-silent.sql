-- title: Central silent
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-silent.md
-- interval: 60
-- pending_for: 180
-- resolve_after: 120
-- Central sends its gauges each minute to the Datum of one region. A Central that sent them in the last 14 days and stopped for 5 minutes is down, or its scheduler, workers or Datum token broke.
SELECT {region:String} AS resource_id, '' AS alert_key, toFloat64(dateDiff('second', last_ts, now())) AS value,
       concat('no Central metrics for ', toString(round(value / 60)), ' min') AS detail
FROM (
    SELECT max(ts) AS last_ts, count() AS samples
    FROM datum.samples
    WHERE resource_id = 'central' AND metric = 'central_job_queue_length' AND ts > now() - INTERVAL 14 DAY
)
WHERE samples > 0 AND last_ts < now() - INTERVAL 5 MINUTE
