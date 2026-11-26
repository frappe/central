-- title: Central site renames failing
-- description: Sites do not get the name the customer chose. Pilot refused the rename, kept answering 401 for an hour, or the Pilot task failed.
-- severity: Medium
-- resource_type: Central
-- interval: 60
-- pending_for: 60
-- resolve_after: 3600
-- One failure is enough: a new site must always get its chosen name. Central writes the Error Log "Pilot site rename failed" for each failure, with the Site as its reference. A 401 writes it only when the retries stop, one hour after the claim.
-- affected names each failed Site. An operator retries it with Retry Site Rename on the Site.
SELECT 'central' AS resource_id, 'site-rename' AS alert_key, toFloat64(failed_sites) AS value,
       concat(toString(failed_sites), ' sites failed to rename in 1 h') AS detail, affected
FROM (
    SELECT count() AS failed_sites,
           mapFromArrays(groupArray(50)(site), groupArray(50)(concat('failed at ', toString(failed_at)))) AS affected
    FROM (
        SELECT attributes['reference_name'] AS site, max(ts) AS failed_at
        FROM datum.logs
        WHERE resource_id = 'central' AND product = 'central' AND source = 'error_log'
          AND message = 'Pilot site rename failed' AND ts > now() - INTERVAL 1 HOUR
        GROUP BY site
    )
)
WHERE failed_sites > 0
