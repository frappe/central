-- title: Central server and site actions failing
-- description: Server and site actions fail or do not finish. Customers cannot create, start or resize their resources.
-- severity: High
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-resource-actions.md
-- charts: central-resource-actions, central-oldest-work
-- interval: 60
-- pending_for: 120
-- resolve_after: 600
-- Resource actions create, start, stop, resize and terminate customer servers and sites. One alert for each region, resource type and action.
-- 3 failed or timed out actions that are 20% of the finished ones in 1 h page. An action open for 30 min is Medium, for 2 h it pages.
-- affected names the newest failed resources with their error code, from central_resource_action_failed.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, a.alert_key AS alert_key, toFloat64(failed) AS value, detail, severity, f.affected AS affected
FROM (
    SELECT concat('failing:', labels['region'], ':', labels['resource_type'], ':', labels['action']) AS alert_key,
           sumIf(value, labels['status'] != 'Succeeded') AS failed,
           concat(toString(failed), ' of ', toString(sum(value)), ' ', labels['resource_type'], ' ', labels['action'], ' actions in ', labels['region'], ' failed in 1 h (limit 20%)') AS detail,
           'High' AS severity
    FROM datum.samples_recent
    WHERE metric = 'central_resource_actions_finished_last_hour' AND resource_id = 'central' AND ts = snapshot
    GROUP BY labels['region'], labels['resource_type'], labels['action']
    HAVING failed >= 3 AND failed >= 0.2 * sum(value)
    UNION ALL
    SELECT concat('stuck:', labels['region'], ':', labels['resource_type'], ':', labels['action']), value,
           concat('a ', labels['resource_type'], ' ', labels['action'], ' action in ', labels['region'], ' is open for ', toString(round(value / 60)), ' min (limit 30 min)'),
           if(value > 7200, 'High', 'Medium')
    FROM datum.samples_recent
    WHERE metric = 'central_resource_action_oldest_open_seconds' AND resource_id = 'central' AND ts = snapshot AND value > 1800
) AS a
LEFT JOIN (
    SELECT concat('failing:', labels['region'], ':', labels['resource_type'], ':', labels['action']) AS alert_key,
           mapFromArrays(groupArray(20)(labels['resource']), groupArray(20)(labels['error'])) AS affected
    FROM datum.samples_recent
    WHERE metric = 'central_resource_action_failed' AND resource_id = 'central' AND ts = snapshot
    GROUP BY alert_key
) AS f ON f.alert_key = a.alert_key
