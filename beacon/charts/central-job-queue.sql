-- title: Central Job Queue
-- resource_type: Region
-- section: Central
-- unit:
-- style: Line
-- is_key_chart: 0
-- sort_order: 20
-- The jobs that wait in each queue of Central, as the central-background-work rule reads them.
SELECT toStartOfInterval(s.ts, toIntervalSecond({step:UInt32})) AS ts, s.labels['queue'] AS series, max(s.value) AS value
FROM datum.samples AS s
WHERE s.metric = 'central_job_queue_length' AND s.resource_id = 'central'
    AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
GROUP BY ts, series
ORDER BY ts, series
