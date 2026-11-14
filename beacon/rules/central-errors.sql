-- title: Central errors
-- severity: Medium
-- resource_type: Region
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- Central sends its Error Logs to the Datum of one region. One alert for each unhandled error fingerprint that repeats 5 times in 15 min. Errors that Central logs on purpose are handled, and the Central gauges cover their work. A PermissionError is a caller without access, not a Central failure.
SELECT {region:String} AS resource_id, fingerprint AS alert_key, toFloat64(errors) AS value,
       concat(toString(errors), ' x ', first_message, ' in Central in 15 min') AS detail
FROM (
    SELECT if(attributes['fingerprint'] = '', left(message, 200), attributes['fingerprint']) AS fingerprint,
           count() AS errors, any(message) AS first_message
    FROM datum.logs
    WHERE resource_id = 'central' AND product = 'central' AND source = 'error_log' AND attributes['unhandled'] = '1'
      AND attributes['exception'] != 'frappe.exceptions.PermissionError' AND ts > now() - INTERVAL 15 MINUTE
    GROUP BY fingerprint
)
WHERE errors >= 5
