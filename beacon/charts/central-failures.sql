-- title: Central Failed Work
-- resource_type: Region
-- section: Central
-- unit:
-- style: Line
-- is_key_chart: 0
-- sort_order: 40
-- The failed items of each kind. Each series name gives the time that Central counts over. Invoices not synced counts all invoices whose sync to ERPNext failed.
SELECT toStartOfInterval(sample_ts, toIntervalSecond({step:UInt32})) AS ts, series, max(items) AS value
FROM (
    SELECT s.ts AS sample_ts,
           multiIf(s.metric = 'central_emails_failed_last_hour', 'Emails, 1 h',
                   s.metric = 'central_site_domains_failed_last_hour', concat(s.labels['route_type'], ' routes, 1 h'),
                   s.metric = 'central_vm_snapshots_failed_last_day', 'VM snapshots, 1 day',
                   s.metric = 'central_invoices_sync_failed', 'Invoices not synced',
                   s.labels['status'] = 'Exhausted', 'Webhook requests given up, 1 day',
                   'Webhook requests retrying, 1 day') AS series,
           sum(s.value) AS items
    FROM datum.samples AS s
    WHERE (s.metric IN ('central_emails_failed_last_hour', 'central_site_domains_failed_last_hour', 'central_vm_snapshots_failed_last_day', 'central_invoices_sync_failed')
           OR (s.metric = 'frappe_webhook_requests_last_day' AND s.labels['status'] IN ('Failed', 'Exhausted')))
        AND s.resource_id = 'central'
        AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
    GROUP BY sample_ts, series
)
GROUP BY ts, series
ORDER BY ts, series
