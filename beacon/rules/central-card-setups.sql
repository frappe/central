-- title: Central card setups or trial conversions failing
-- description: A customer cannot add a card or UPI, or added one and their trial did not convert. The customer cannot pay.
-- severity: Medium
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-card-setups.md
-- charts: central-card-setups
-- interval: 60
-- pending_for: 60
-- resolve_after: 900
-- A failed setup is one that the gateway saved and Central's check rejected, such as an Indian mandate that is not active. Each one is a customer who cannot pay, so 1 in 1 h alerts.
-- A team that started 2 or more setups in 1 h and finished none keeps trying, and its card does not save. A setup that the customer leaves open expires after a day and does not alert.
-- An active trial whose team has an active card for 10 min did not convert, and its trial error says why. A converted trial whose server still runs a trial plan did not move to its paid plan.
-- affected names the teams with their failure code, from central_card_setup_failed.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, a.alert_key AS alert_key, a.value AS value, a.detail AS detail, f.affected AS affected
FROM (
    SELECT concat('failed:', gateway) AS alert_key, failed AS value,
           concat(toString(failed), ' ', gateway, ' card or UPI setups failed in 1 h (limit 1)') AS detail
    FROM (
        SELECT labels['gateway'] AS gateway, sum(value) AS failed
        FROM datum.samples_recent
        WHERE metric = 'central_card_setups_last_hour' AND resource_id = 'central' AND ts = snapshot AND labels['outcome'] = 'failed'
        GROUP BY gateway
    )
    WHERE failed >= 1
    UNION ALL
    SELECT concat('unfinished:', labels['team']), value,
           concat(labels['team'], ' started ', toString(value), ' card or UPI setups in 1 h and finished none (limit 2)')
    FROM datum.samples_recent
    WHERE metric = 'central_card_setup_unfinished_attempts' AND resource_id = 'central' AND ts = snapshot
    UNION ALL
    SELECT 'conversion-blocked', blocked, concat(toString(blocked), ' active trials have a card for 10 min and did not convert: ', reasons)
    FROM (
        SELECT sum(value) AS blocked, arrayStringConcat(groupArray(5)(labels['reason']), '; ') AS reasons
        FROM datum.samples_recent
        WHERE metric = 'central_trial_conversions_blocked' AND resource_id = 'central' AND ts = snapshot
    )
    WHERE blocked >= 1
    UNION ALL
    SELECT 'conversion-unmoved', value, concat(toString(value), ' converted trials still run a trial plan')
    FROM datum.samples_recent
    WHERE metric = 'central_trial_conversions_unmoved' AND resource_id = 'central' AND ts = snapshot AND value >= 1
) AS a
LEFT JOIN (
    SELECT concat('failed:', labels['gateway']) AS alert_key,
           mapFromArrays(groupArray(20)(labels['team']), groupArray(20)(labels['code'])) AS affected
    FROM datum.samples_recent
    WHERE metric = 'central_card_setup_failed' AND resource_id = 'central' AND ts = snapshot
    GROUP BY alert_key
) AS f ON f.alert_key = a.alert_key
