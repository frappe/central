# Central refactor backlog

## Purpose

This document lists the cleanup work that is still open after the v0.2 refactor. All earlier phases are complete.

## Open work

| Item | Why it is open | Condition to start |
|---|---|---|
| Upstream restart-completion contract (deferred) | The region publishes no restart counter. Resource Action waits for one observed state change away from Running before Running can complete a restart. | Atlas publishes an authoritative restart completion signal, such as an operation generation. |
| Rename `cluster:view` (deferred) | It is stored authorization vocabulary. Fixtures, `central/iam.py`, the API, and the dashboard use it. | A stored-grant migration and a coordinated consumer update are ready in the same change. |

Record a new structural or product decision here before you implement it. Ordinary simplification within agreed behavior does not need a new entry.
