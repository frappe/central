-- title: Central Requests
-- resource_type: Region
-- section: Central
-- unit: req/s
-- style: Line
-- is_key_chart: 0
-- sort_order: 10
-- Central is global and sends to the region with Central Telemetry Region set, so other regions show no data. Each sample counts the requests since the one before it.
SELECT toStartOfInterval(s.ts, toIntervalSecond({step:UInt32})) AS ts, s.labels['status_class'] AS series, sum(s.value) / {step:UInt32} AS value
FROM datum.samples AS s
WHERE s.metric = 'central_requests' AND s.resource_id = 'central'
    AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
GROUP BY ts, series
ORDER BY ts, series
