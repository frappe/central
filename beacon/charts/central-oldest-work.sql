-- title: Central Oldest Open Work
-- resource_type: Region
-- section: Central
-- unit: min
-- style: Line
-- is_key_chart: 0
-- sort_order: 30
-- The age of the oldest open item of each kind, and the latest scheduled job. Each one grows when its work stops.
SELECT toStartOfInterval(s.ts, toIntervalSecond({step:UInt32})) AS ts,
       multiIf(s.metric = 'central_billing_run_oldest_open_seconds', 'Billing run',
               s.metric = 'central_resource_action_oldest_open_seconds', 'Resource action',
               s.metric = 'central_email_oldest_unsent_seconds', 'Unsent email',
               s.metric = 'central_site_domain_oldest_pending_seconds', 'Site domain',
               s.metric = 'central_vm_snapshot_oldest_pending_seconds', 'VM snapshot',
               'Late scheduled job') AS series,
       max(s.value) / 60 AS value
FROM datum.samples AS s
WHERE s.metric IN ('central_billing_run_oldest_open_seconds', 'central_resource_action_oldest_open_seconds', 'central_email_oldest_unsent_seconds',
                   'central_site_domain_oldest_pending_seconds', 'central_vm_snapshot_oldest_pending_seconds', 'central_scheduled_job_late_seconds')
    AND s.resource_id = 'central'
    AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
GROUP BY ts, series
ORDER BY ts, series
