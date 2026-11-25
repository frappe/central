-- title: Central signups failing or slow
-- description: A new customer's trial site fails, waits too long, or does not get its app. The customer leaves before they try the product.
-- severity: Medium
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-signups.md
-- charts: central-signup-funnel, central-signup-setup-time
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- A signup must not fail, so 1 failed trial site in 1 h is Medium and 3 page. A trial site that waits 5 min is Medium and 15 min pages, because a ready site usually takes under 1 min.
-- A median setup time over 2 min for 30 min is Medium, so a slow rise shows before a customer waits. A trial app install that failed in 1 h is Medium.
-- affected names the newest failed trial sites with their error code, from central_signup_failed.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, a.alert_key AS alert_key, a.value AS value, a.detail AS detail, a.severity AS severity, f.affected AS affected
FROM (
    SELECT 'failed' AS alert_key, failed AS value, concat(toString(failed), ' trial sites failed in 1 h (limit 1)') AS detail,
           if(failed >= 3, 'High', 'Medium') AS severity
    FROM (
        SELECT sum(value) AS failed
        FROM datum.samples_recent
        WHERE metric = 'central_signup_steps_last_hour' AND resource_id = 'central' AND ts = snapshot AND labels['step'] = 'failed'
    )
    WHERE failed >= 1
    UNION ALL
    SELECT concat('waiting:', labels['region']), value,
           concat('a trial site in ', labels['region'], ' waits for ', toString(round(value / 60)), ' min (limit 5 min)'),
           if(value > 900, 'High', 'Medium')
    FROM datum.samples_recent
    WHERE metric = 'central_signup_oldest_waiting_seconds' AND resource_id = 'central' AND ts = snapshot AND value > 300
    UNION ALL
    SELECT concat('slow:', region), fastest,
           concat('trial sites in ', region, ' took a median of over ', toString(round(fastest)), ' s for 30 min (limit 120 s)'), 'Medium'
    FROM (
        SELECT labels['region'] AS region, min(value) AS fastest, count() AS samples
        FROM datum.samples_recent
        WHERE metric = 'central_signup_setup_seconds' AND resource_id = 'central' AND labels['quantile'] = 'p50'
          AND ts > now() - INTERVAL 30 MINUTE
        GROUP BY region
    )
    WHERE samples >= 20 AND fastest > 120
    UNION ALL
    SELECT 'app-install', toFloat64(installs), concat(toString(installs), ' trial app installs failed in 1 h (limit 1): ', sites), 'Medium'
    FROM (
        SELECT count() AS installs, arrayStringConcat(groupUniqArray(5)(attributes['reference_name']), ', ') AS sites
        FROM datum.logs
        WHERE resource_id = 'central' AND product = 'central' AND source = 'error_log' AND message = 'Trial app install failed'
          AND ts > now() - INTERVAL 1 HOUR
    )
    WHERE installs >= 1
) AS a
LEFT JOIN (
    SELECT 'failed' AS alert_key, mapFromArrays(groupArray(20)(labels['site']), groupArray(20)(labels['error'])) AS affected
    FROM datum.samples_recent
    WHERE metric = 'central_signup_failed' AND resource_id = 'central' AND ts = snapshot
) AS f ON f.alert_key = a.alert_key
