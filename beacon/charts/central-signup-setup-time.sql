-- title: Central Signup Setup Time
-- resource_type: Region
-- section: Central
-- unit: s
-- style: Line
-- is_key_chart: 0
-- sort_order: 70
-- The median and the longest time from a trial request to a ready site, over the hour before each sample, and the trial that waits longest now. The central-signups rule reads the same gauges.
SELECT toStartOfInterval(s.ts, toIntervalSecond({step:UInt32})) AS ts,
       multiIf(s.metric = 'central_signup_oldest_waiting_seconds', concat('Waiting ', s.labels['region']),
               s.labels['quantile'] = 'p50', concat('Median ', s.labels['region']),
               concat('Longest ', s.labels['region'])) AS series,
       max(s.value) AS value
FROM datum.samples AS s
WHERE s.metric IN ('central_signup_setup_seconds', 'central_signup_oldest_waiting_seconds') AND s.resource_id = 'central'
    AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
GROUP BY ts, series
ORDER BY ts, series
