-- title: Central cannot deliver webhooks
-- description: Central cannot deliver webhooks to other services. Events such as VM state changes do not arrive.
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-webhooks-failing.md
-- charts: central-failures
-- interval: 300
-- pending_for: 600
-- resolve_after: 1800
-- Central sends events to other services with Frappe webhooks. Exhausted means Frappe gave up after its retries, so the receiver never got the event.
-- affected names the newest exhausted documents with the last line of their error, from frappe_webhook_request_exhausted.
-- 10 exhausted requests that are 20% of the requests of one webhook in 1 day page. One exhausted request, or 10 that still retry, is Medium.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, w.webhook AS alert_key, toFloat64(exhausted) AS value,
       concat(toString(exhausted), ' of ', toString(total), ' ', webhook, ' requests failed after retries in 1 day; ', toString(retrying), ' still retry (limit 20%)') AS detail,
       if(exhausted >= 10 AND exhausted >= 0.2 * total, 'High', 'Medium') AS severity,
       e.affected AS affected
FROM (
    SELECT labels['webhook'] AS webhook, sumIf(value, labels['status'] = 'Exhausted') AS exhausted, sumIf(value, labels['status'] = 'Failed') AS retrying, sum(value) AS total
    FROM datum.samples_recent
    WHERE metric = 'frappe_webhook_requests_last_day' AND resource_id = 'central' AND ts = snapshot
    GROUP BY webhook
) AS w
LEFT JOIN (
    SELECT labels['webhook'] AS webhook,
           mapFromArrays(groupArray(20)(labels['document']), groupArray(20)(labels['error'])) AS affected
    FROM datum.samples_recent
    WHERE metric = 'frappe_webhook_request_exhausted' AND resource_id = 'central' AND ts = snapshot
    GROUP BY webhook
) AS e ON e.webhook = w.webhook
WHERE exhausted > 0 OR retrying >= 10
