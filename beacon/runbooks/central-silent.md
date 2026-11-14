# Central silent

Central sends its gauges to the Datum of one region each minute. They stopped for 5 minutes. Central is down, or its scheduler, its workers or its Datum token broke. Beacon can also not see Central errors now.

1. Open the Central dashboard. When it does not load, Central is down: check the Central server and its web workers first.
2. When the dashboard loads, check the scheduler: `bench --site <site> doctor`. Look for a disabled scheduler or stopped workers.
3. Check the Central logs for `Datum push to /v1/ingest failed`. A failed push means the telemetry host of the region is down or refuses the Central token.
4. When Central is down for customers, open a public incident.
