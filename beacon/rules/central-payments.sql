-- title: Central payments failing
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-payments.md
-- interval: 60
-- pending_for: 120
-- resolve_after: 600
-- 5 failed payments that are half of the attempts of a gateway in 1 h page. A gateway webhook waiting for 15 min pages, because the money arrived but the credit is not applied. A failed webhook is Medium. No capture for 1 day is Low.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, alert_key, toFloat64(failed) AS value, detail, severity
FROM (
    SELECT concat('attempts:', labels['gateway']) AS alert_key, sumIf(value, labels['status'] = 'Failed') AS failed,
           concat(toString(failed), ' of ', toString(sum(value)), ' payments through ', labels['gateway'], ' failed in 1 h') AS detail, 'High' AS severity
    FROM datum.samples_recent
    WHERE metric = 'central_payment_attempts_last_hour' AND resource_id = 'central' AND ts = snapshot
    GROUP BY labels['gateway']
    HAVING failed >= 5 AND failed >= 0.5 * sum(value)
    UNION ALL
    SELECT concat('webhooks-waiting:', labels['gateway']), value, concat('a ', labels['gateway'], ' webhook waits for ', toString(round(value / 60)), ' min'), 'High'
    FROM datum.samples_recent
    WHERE metric = 'central_gateway_webhook_oldest_unprocessed_seconds' AND resource_id = 'central' AND ts = snapshot AND value > 900
    UNION ALL
    SELECT concat('webhooks-failed:', labels['gateway']), value, concat(toString(value), ' ', labels['gateway'], ' webhooks failed in 1 h'), 'Medium'
    FROM datum.samples_recent
    WHERE metric = 'central_gateway_webhooks_failed_last_hour' AND resource_id = 'central' AND ts = snapshot AND value > 0
    UNION ALL
    SELECT concat('no-capture:', labels['gateway']), value, concat('no payment captured through ', labels['gateway'], ' for ', toString(round(value / 3600)), ' h'), 'Low'
    FROM datum.samples_recent
    WHERE metric = 'central_payment_last_capture_seconds' AND resource_id = 'central' AND ts = snapshot AND value > 86400
)
