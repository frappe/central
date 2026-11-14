-- title: Central API errors
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-api-errors.md
-- interval: 60
-- pending_for: 120
-- resolve_after: 300
-- Customers use the Central API and dashboard. More than 5% 5xx in 10 min (at least 50 requests) pages. More than 1% in 1 h is Medium. One group with 10 errors and more than 10% of its requests is Medium.
SELECT {region:String} AS resource_id, alert_key, value, detail, severity
FROM (
    SELECT 'all' AS alert_key, errors_10m / requests_10m AS value,
           concat(toString(errors_10m), ' of ', toString(requests_10m), ' Central API requests failed with 5xx in 10 min') AS detail,
           'High' AS severity
    FROM (
        SELECT sumIf(value, ts > now() - INTERVAL 10 MINUTE AND labels['status_class'] = '5xx') AS errors_10m,
               sumIf(value, ts > now() - INTERVAL 10 MINUTE) AS requests_10m
        FROM datum.samples_recent
        WHERE resource_id = 'central' AND metric = 'central_requests' AND ts > now() - INTERVAL 10 MINUTE
    )
    WHERE requests_10m >= 50 AND errors_10m > 0.05 * requests_10m
    UNION ALL
    SELECT 'hourly', errors / requests, concat(toString(errors), ' of ', toString(requests), ' Central API requests failed with 5xx in 1 h'), 'Medium'
    FROM (
        SELECT sumIf(value, labels['status_class'] = '5xx') AS errors, sum(value) AS requests
        FROM datum.samples_recent
        WHERE resource_id = 'central' AND metric = 'central_requests' AND ts > now() - INTERVAL 1 HOUR
    )
    WHERE requests >= 200 AND errors > 0.01 * requests
    UNION ALL
    SELECT concat('group:', api_group), errors / requests, concat(toString(errors), ' of ', toString(requests), ' ', api_group, ' requests failed with 5xx in 10 min'), 'Medium'
    FROM (
        SELECT labels['group'] AS api_group, sumIf(value, labels['status_class'] = '5xx') AS errors, sum(value) AS requests
        FROM datum.samples_recent
        WHERE resource_id = 'central' AND metric = 'central_requests' AND ts > now() - INTERVAL 10 MINUTE
        GROUP BY api_group
    )
    WHERE errors >= 10 AND errors > 0.1 * requests
)
