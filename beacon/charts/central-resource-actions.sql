-- title: Central Finished Actions
-- resource_type: Region
-- section: Central
-- unit:
-- style: Bar
-- is_key_chart: 0
-- sort_order: 50
-- The server and site actions that finished in the hour before each sample, by result, as the central-resource-actions rule reads them.
SELECT toStartOfInterval(sample_ts, toIntervalSecond({step:UInt32})) AS ts, series, max(actions) AS value
FROM (
    SELECT s.ts AS sample_ts, s.labels['status'] AS series, sum(s.value) AS actions
    FROM datum.samples AS s
    WHERE s.metric = 'central_resource_actions_finished_last_hour' AND s.resource_id = 'central'
        AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
    GROUP BY sample_ts, series
)
GROUP BY ts, series
ORDER BY ts, series
