-- title: Central background work stuck
-- severity: Medium
-- resource_type: Region
-- runbook_url: https://github.com/frappe/central/blob/develop/beacon/runbooks/central-background-work.md
-- interval: 300
-- pending_for: 600
-- resolve_after: 900
-- Central work that customers wait for, but that no request shows. One alert for each check: a billing run open for 1 day, a proxy route pending for 30 min,
-- 3 proxy routes that failed in 1 h, an automatic snapshot that failed today, a snapshot pending for 2 h, 5 failed emails in 1 h, an email waiting for 30 min,
-- a scheduled job 15 min late, or 1,000 queued jobs. Invoices that fail to sync to accounting are Low. Failed jobs show in central-errors.
-- Central sends all gauges of one collection with one timestamp. The rule reads only the newest collection, so a series that Central stopped sending, because its problem cleared, does not keep the alert.
WITH (SELECT max(ts) FROM datum.samples_recent WHERE metric = 'central_job_queue_length' AND resource_id = 'central' AND ts > now() - INTERVAL 10 MINUTE) AS snapshot
SELECT {region:String} AS resource_id, alert_key, value, concat(alert_key, ': ', toString(round(value))) AS detail,
       if(alert_key = 'invoice-sync', 'Low', 'Medium') AS severity
FROM (
    SELECT multiIf(
               metric = 'central_billing_run_oldest_open_seconds' AND value > 86400, 'billing-run-open-seconds',
               metric = 'central_site_domain_oldest_pending_seconds' AND value > 1800, concat('route-pending-seconds:', labels['route_type']),
               metric = 'central_site_domains_failed_last_hour' AND value >= 3, concat('routes-failed-in-1h:', labels['route_type']),
               metric = 'central_vm_snapshots_failed_last_day' AND labels['snapshot_type'] = 'Automatic' AND value > 0, 'automatic-snapshots-failed-today',
               metric = 'central_vm_snapshot_oldest_pending_seconds' AND value > 7200, 'snapshot-pending-seconds',
               metric = 'central_emails_failed_last_hour' AND value >= 5, 'emails-failed-in-1h',
               metric = 'central_email_oldest_unsent_seconds' AND value > 1800, 'email-waiting-seconds',
               metric = 'central_scheduled_job_late_seconds' AND value > 900, concat('job-late-seconds:', labels['job']),
               metric = 'central_job_queue_length' AND value >= 1000, concat('queued-jobs:', labels['queue']),
               metric = 'central_invoices_sync_failed' AND value > 0, 'invoice-sync',
               '') AS alert_key,
           value
    FROM datum.samples_recent
    WHERE resource_id = 'central' AND ts = snapshot AND metric IN (
        'central_billing_run_oldest_open_seconds', 'central_site_domain_oldest_pending_seconds', 'central_site_domains_failed_last_hour',
        'central_vm_snapshots_failed_last_day', 'central_vm_snapshot_oldest_pending_seconds', 'central_emails_failed_last_hour',
        'central_email_oldest_unsent_seconds', 'central_scheduled_job_late_seconds', 'central_job_queue_length', 'central_invoices_sync_failed')
)
WHERE alert_key != ''
