-- title: Central errors
-- severity: Medium
-- resource_type: Region
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- Central sends its Error Logs to the Datum of one region. One alert for each unhandled error fingerprint that repeats 5 times in 15 min. Errors that Central logs on purpose are handled, and the Central gauges cover their work. A PermissionError is a caller without access, not a Central failure.
SELECT {region:String} AS resource_id, if(attributes['fingerprint'] = '', left(message, 200), attributes['fingerprint']) AS alert_key, count() AS value,
       concat(toString(value), ' x ', any(message), ' in Central in 15 min') AS detail
FROM datum.logs
WHERE product = 'central' AND source = 'error_log' AND attributes['unhandled'] = '1' AND ts > now() - INTERVAL 15 MINUTE
  AND attributes['exception'] != 'frappe.exceptions.PermissionError'
GROUP BY alert_key
HAVING value >= 5
