---
name: performance-inspection
description: Finds why a customer site or server is slow, for L1, L2, and L4 support. Runs an automated pass over server resources, service processes, slow requests, jobs, reports, and MariaDB queries, locks, and indexes, then explains the top slow queries and gives the support action or the developer fix. Use when a site is slow, requests time out, jobs are late, or a server has high CPU, memory, or disk use.
---

# Inspect performance

Find the bottleneck, the work that causes it, and the fix. Run the steps without asking the user. Ask only when you cannot find the server or the site.

Do not show code or SQL to support staff. Name the page, report, DocType, and field instead. Put the exact query only in the developer section of the report.

## Rules

- Use measured evidence. One metric is not proof of a cause.
- Rank work by total time (count x average time), not by the slowest single run.
- Match the window to the incident: `30m`, `1h`, `6h`, `12h`, `24h`, or `1w`. If the incident time is not known, use `1h`, then `24h`.
- Recommend an index only when `EXPLAIN` shows a full scan or a large row estimate on a large table.
- Do not resize a server, add an index, or kill a query as a general fix.
- Stop when the top 3 items of work are explained, or when the evidence is blocked.

## Workflow

```text
1. Snapshot
2. Find the bottleneck
3. Find the work that causes it
4. Explain the top queries
5. Fix
6. Validate and report
```

### 1. Snapshot

Find the server, and the site if one is named. Call `get_performance_snapshot` with the server, the site, and the window. One call reads the server, the services, the database, and the site.

Read more paths with `send_pilot_read_request` only when the snapshot does not answer a question.

### 2. Find the bottleneck

Use `monitor/status` and `monitor/history`. The CPU breakdown has `user`, `system`, `iowait`, `irq`, `other`, and `idle`. `other` is CPU steal by the host. Each service process has `cpu_percent`, `memory_rss_bytes`, `read_bytes`, and `write_bytes`.

Use these thresholds as a start. Each one must hold for most of the window, not for one sample.

| Observation | Bottleneck | Next |
| --- | --- | --- |
| `other` above 10% | Host | Step 5, hand to Atlas |
| `iowait` above 20% | Disk | Find the process with the most `read_bytes` and `write_bytes` |
| `user` + `system` above 85% | CPU | Find the process with the most `cpu_percent` |
| Memory above 90%, and swap grows | Memory | Find the process with the most `memory_rss_bytes` |
| Disk space above 90% | Disk space | Read `storage` and `database/table-sizes` |
| Resources normal, requests slow | Waits | Check `database/lockwaits`, `database/processlist`, and the task worker |

If the top process is MariaDB, the bottleneck is database work. Go to step 3.

### 3. Find the work

Use `sites/<site>/monitoring` from the snapshot. It has the slowest requests, jobs, and reports, the slowest queries, and the most frequent slow queries.

- Rank each list by total time. A request of 2 seconds that runs 5000 times is worse than one of 60 seconds that runs once.
- Match each item to a page, report, background job, or DocType.
- `database/processlist`: a query that runs for more than 30 seconds, or many copies of the same query, is a strong signal.
- `database/lockwaits`: name the blocking query and the waiting queries. A lock wait is not a slow query. Fix the blocker.
- `database/performance-report` `full_table_scan_queries`: a full scan matters only on a large table that is read often.
- For job delays, read `task-worker` and `tasks` with `{"status": "failed"}`. Pilot does not show queue wait time.

### 4. Explain the top queries

For the top 3 queries by total time, call `run_database_query`:

1. `EXPLAIN <query>`. If the query has `?` placeholders, put in a real value from the slow query sample.
2. `SHOW INDEX FROM <table>` for each table with `type` `ALL`, or with a large `rows` value.
3. Read the table size from `database/table-sizes`.

| `EXPLAIN` result | Meaning | Fix |
| --- | --- | --- |
| `type` `ALL` on a table with more than 10000 rows | Full scan | Index on the filter fields: equality fields first, then range or sort fields |
| `Using filesort` on a large result | Sort without an index | Add the sort field to the end of the index |
| An index exists but `key` is NULL | The index is not used | Look for a function on the field, such as COALESCE, or a type mismatch |
| `rows` is small | The query is not the cause | Look at how often it runs, or at lock waits |

Do not run a slow query without `EXPLAIN`. The query tool stops a query after 10 seconds.

### 5. Fix

Support makes a change only after the user switches the session to read-write. Follow the Fix step of `server-support-guide`.

| Finding | Fix | Tool |
| --- | --- | --- |
| A runaway query blocks other work | Stop that query. Read `database/processlist` first to get its `process_id` | `send_pilot_write_request` `POST database/processlist/kill` with `{"process_id": <id>}` |
| A bench is stuck after the cause is gone | Restart the bench. Check `tasks` for running work first | `send_pilot_write_request` `POST benches/<bench>/actions/restart` |
| Normal work is more than the server can do | Resize the server. Only a larger disk is allowed | `call_central_api` `central.api.servers.resize_server` with `plan`, or `disk_gigabytes` |
| The host is the bottleneck | Hand to Atlas with the server, the window, and the CPU breakdown | `start_region_investigation` |

Fixes for the customer's developer. Support gives these. Support does not make them:

- **Index:** name the DocType and the fields in order. Customize Form adds an index on one field. An index on 2 or more fields is added with the bench command for a database index. Both stay after a migrate or a restore.
- **Too many indexes:** `unused_indexes` and `redundant_indexes` slow down inserts. Remove one only after a full week of data.
- **Report filter:** a function on a filter field, such as COALESCE, stops the database from using the index.
- **Slow page:** use the Recorder in the site on version 15 and later.
- **Frequent work:** cache or batch a request or job that runs thousands of times.

### 6. Validate and report

After a fix, call `get_performance_snapshot` again with the same window. Compare the same numbers before and after. If you made no change, say that validation waits for the fix.

Report with the Incident found template of `virtual-machine-investigation`. Put the top items of work in its resource table:

| Work | Type | Count | Average | Total | Cause |
| --- | --- | --- | --- | --- | --- |
| <page, report, job, or DocType> | <request, job, report, query> | <n> | <ms> | <s> | <full scan, lock wait, CPU> |

Add a **For the developer** section with each exact query, its `EXPLAIN` row, and the index to add.

If the evidence does not show a cause, say what is missing. Do not invent a cause.
