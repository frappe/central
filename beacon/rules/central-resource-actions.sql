-- title: Central resource actions failing
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-resource-actions.md
-- interval: 60
-- pending_for: 120
-- resolve_after: 600
-- Resource actions create, start, stop, resize and terminate customer servers and sites. One alert for each region, resource type and action.
-- 3 failed or timed out actions that are 20% of the finished ones in 1 h page. An action open for 30 min is Medium, for 2 h it pages.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, alert_key, toFloat64(failed) AS value, detail, severity
FROM (
    SELECT concat('failing:', labels['region'], ':', labels['resource_type'], ':', labels['action']) AS alert_key,
           sumIf(value, labels['status'] != 'Succeeded') AS failed,
           concat(toString(failed), ' of ', toString(sum(value)), ' ', labels['resource_type'], ' ', labels['action'], ' actions in ', labels['region'], ' failed in 1 h') AS detail,
           'High' AS severity
    FROM datum.samples_recent
    WHERE metric = 'central_resource_actions_finished_last_hour' AND resource_id = 'central' AND ts = snapshot
    GROUP BY labels['region'], labels['resource_type'], labels['action']
    HAVING failed >= 3 AND failed >= 0.2 * sum(value)
    UNION ALL
    SELECT concat('stuck:', labels['region'], ':', labels['resource_type'], ':', labels['action']), value,
           concat('a ', labels['resource_type'], ' ', labels['action'], ' action in ', labels['region'], ' is open for ', toString(round(value / 60)), ' min'),
           if(value > 7200, 'High', 'Medium')
    FROM datum.samples_recent
    WHERE metric = 'central_resource_action_oldest_open_seconds' AND resource_id = 'central' AND ts = snapshot AND value > 1800
)
