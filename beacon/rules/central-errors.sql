-- title: Central throws unhandled errors
-- description: The same unhandled error repeats in Central. The action that a customer tried may fail.
-- severity: Medium
-- resource_type: Region
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- Central sends its Error Logs to the Datum of one region. One alert for each unhandled error fingerprint that repeats 5 times in 15 min. Errors that Central logs on purpose are handled, and the Central gauges cover their work. A PermissionError is a caller without access, not a Central failure.
SELECT {region:String} AS resource_id, fingerprint AS alert_key, toFloat64(errors) AS value,
       concat(toString(errors), ' unhandled errors in 15 min (limit 5): ', first_message) AS detail
FROM (
    SELECT if(attributes['fingerprint'] = '', left(message, 200), attributes['fingerprint']) AS fingerprint,
           count() AS errors, any(message) AS first_message
    FROM datum.logs
    WHERE resource_id = 'central' AND product = 'central' AND source = 'error_log' AND attributes['unhandled'] = '1'
      AND attributes['exception'] != 'frappe.exceptions.PermissionError' AND ts > now() - INTERVAL 15 MINUTE
    GROUP BY fingerprint
)
WHERE errors >= 5
