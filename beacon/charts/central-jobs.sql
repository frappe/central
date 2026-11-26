-- title: Central Failed Jobs
-- resource_type: Region
-- section: Central
-- unit:
-- style: Bar
-- is_key_chart: 0
-- sort_order: 25
-- Background jobs and scheduled job runs that failed in the hour before each sample, as the central-failed-jobs rule reads them.
SELECT toStartOfInterval(sample_ts, toIntervalSecond({step:UInt32})) AS ts, series, max(failed) AS value
FROM (
    SELECT s.ts AS sample_ts,
           if(s.metric = 'central_jobs_failed_last_hour', concat('Background, ', s.labels['queue']), 'Scheduled runs') AS series,
           sum(s.value) AS failed
    FROM datum.samples AS s
    WHERE (s.metric = 'central_jobs_failed_last_hour'
           OR (s.metric = 'central_scheduled_job_runs_last_hour' AND s.labels['status'] = 'Failed'))
        AND s.resource_id = 'central'
        AND s.ts >= {start:DateTime64(3)} AND s.ts < {end:DateTime64(3)}
    GROUP BY sample_ts, series
)
GROUP BY ts, series
ORDER BY ts, series
