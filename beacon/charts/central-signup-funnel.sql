-- title: Central Signup Funnel
-- resource_type: Region
-- section: Central
-- unit:
-- style: Bar
-- is_key_chart: 0
-- sort_order: 60
-- The signup steps in the hour before each sample: new accounts, trial sites requested, ready and failed. A gap between two steps is where customers stop.
SELECT toStartOfInterval(sample_ts, toIntervalSecond({step:UInt32})) AS ts, series, max(steps) AS value
FROM (
    SELECT s.ts AS sample_ts,
           multiIf(s.labels['step'] = 'verified', '1 Account created', s.labels['step'] = 'requested', '2 Trial requested',
                   s.labels['step'] = 'ready', '3 Site ready', '4 Failed') AS series,
           sum(s.value) AS steps
    FROM datum.samples AS s
    WHERE s.metric = 'central_signup_steps_last_hour' AND s.resource_id = 'central'
        AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
    GROUP BY sample_ts, series
)
GROUP BY ts, series
ORDER BY ts, series
