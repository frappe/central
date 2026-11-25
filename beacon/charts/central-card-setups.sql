-- title: Central Card Setups
-- resource_type: Region
-- section: Central
-- unit:
-- style: Bar
-- is_key_chart: 0
-- sort_order: 80
-- Card and UPI setups in the hour before each sample: started, succeeded, failed and expired. Started with few succeeded means customers cannot add a card.
SELECT toStartOfInterval(sample_ts, toIntervalSecond({step:UInt32})) AS ts, series, max(setups) AS value
FROM (
    SELECT s.ts AS sample_ts,
           multiIf(s.labels['outcome'] = 'started', '1 Started', s.labels['outcome'] = 'succeeded', '2 Succeeded',
                   s.labels['outcome'] = 'failed', '3 Failed', '4 Expired') AS series,
           sum(s.value) AS setups
    FROM datum.samples AS s
    WHERE s.metric = 'central_card_setups_last_hour' AND s.resource_id = 'central'
        AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
    GROUP BY sample_ts, series
)
GROUP BY ts, series
ORDER BY ts, series
