# Inbound webhooks

## Purpose

This document is the contract for a region that reports to Central. Atlas reports what its virtual machines do. Cargo reports what its regional services serve.

Central accepts these reports at one endpoint. A sender never calls any other Central route.

Outbound is the other direction and not this contract: the one Webhook Central sends, a team's tier to Grove, is Frappe's own `Webhook` doctype, kept by AI Settings (`central/services/doctype/ai_settings/SPEC.md`).

```text
Atlas  ──┐
         ├── POST /api/method/central.api.state_delivery.receive
Cargo  ──┘
```

## Endpoint

| Item | Value |
|---|---|
| Method | `POST` |
| Path | `/api/method/central.api.state_delivery.receive` |
| Body | JSON object |
| Authentication | The request signature. There is no session and no API key. |

The route is open to guests because the caller is a region, not a user. Do not send an `Authorization` header. Frappe rejects a two-part `Authorization` value that does not resolve to a user before the route runs.

## Required headers

Each header has one meaning. Central does not infer a source from any other header.

| Header | Value | Use |
|---|---|---|
| `X-FC-Source` | `atlas` or `cargo` | Selects the handler. Case is ignored. |
| `X-FC-Region` | The region name, as Central names it | Selects the secret to check the signature against. |
| `X-Frappe-Webhook-Signature` | Base64 HMAC-SHA256 of the exact bytes sent | Proves the delivery. |

A request without `X-FC-Source`, or with any other value, is refused with HTTP 403. A request without `X-FC-Region` or without a signature is refused with HTTP 403.

`X-FC-Source` and `X-FC-Region` are selectors only. They prove nothing. The signature is the only trusted part of the request.

## Signature

Central verifies `base64(HMAC-SHA256(secret, raw_body))` against the exact bytes of the request body.

A Frappe Webhook produces this when `enable_security` is set and `webhook_secret` holds the shared secret. A sender that builds the request itself must sign the serialized body it sends, byte for byte, before any reformatting.

| Sender | Secret Central checks against | Required state |
|---|---|---|
| `atlas` | `Region.webhook_secret` for the named region | Status is not `Disabled` |
| `cargo` | `Region.cargo_webhook_secret` for the named region | `cargo_status` is `Registered` |

Central answers every failed check with the same sentence, `Invalid signature.`, and HTTP 403. The reason is written to the Error Log for the operator. A sender cannot learn from the reply whether the region was unknown, the secret was missing, or the signature was wrong.

## Atlas reports

Atlas reports one virtual machine per delivery.

| Field | Required | Value |
|---|---|---|
| `event` | Yes | `vm.state` or `vm.state.deleted` |
| `virtual_machine` | Yes | The Atlas VM ID. Central matches it to a Virtual Machine in the signing region. |
| `status` | For `vm.state` | `running`, `stopped`, or `paused` |
| `observed_at` | For `vm.state` | The region's own timestamp. Central orders reports by it and drops one that is not newer. |

Planned abuse protection adds the `vm.network` event. See [Planned: `vm.network`](#planned-vmnetwork).

For `vm.state`, Central records `running` as `Running`, `stopped` as `Stopped`, and `paused` as `Paused`. Central never records a status it was not told.

Atlas sends `vm.state.deleted` after Metal confirms that the machine is absent. Central records the server as `Terminated`, closes its billing, revokes its Pilot credentials, and completes a waiting terminate action. Termination is final, so Central ignores `status` and `observed_at` on this event and does no ordering check. A lost deletion is corrected by a scoped read that answers not found. See [resource actions](../central/infrastructure/doctype/resource_action/SPEC.md).

An accepted report is applied by a background job, not in the request. The reply is a receipt, not a confirmation.

```json
{"queued": true, "resource_id": "vm-0a1b2c3d4e"}
```

### Planned: `vm.network`

Atlas sends `vm.network` when one of three fields of the Atlas Virtual Machine State changes: `network_desired_generation`, `network_observed_generation`, or `network_error`. These fields mirror Metal. So Central learns when Metal applies a change, when Metal reports an error, and when an Atlas operator changes a restriction. The generations belong to the complete VM spec, so a change that is not a network change also sends the event. Each event costs Central one `GET` VM. See [Atlas events to Central](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#events-to-central).

| Field | Required | Value |
|---|---|---|
| `event` | Yes | `vm.network` |
| `virtual_machine` | Yes | The Atlas VM ID |
| `server` | No | The Atlas host of the VM |
| `desired_generation` | No | The VM spec generation that Atlas sent to Metal |
| `observed_generation` | No | The VM spec generation that Metal applied |
| `host_error` | No | The error that Metal reported, or an empty string |
| `observed_at` | Yes | The region's own timestamp, as in `vm.state` |

```json
{"event": "vm.network", "virtual_machine": "vm-0a1b2c3d4e", "server": "metal-bom-01", "desired_generation": 42, "observed_generation": 42, "host_error": "", "observed_at": "2026-11-12 10:00:05"}
```

- The event is only a trigger. Central reads the Atlas `GET` VM response and runs the steps of its repair scan for the VM. It does not record the status of the server from this event. See [Restriction states](ABUSE.md#restriction-states) and [Events from Atlas](ABUSE.md#events-from-atlas).
- Central queues one job for each VM. A repeated or late event reads the same state again and changes nothing, so Central does no ordering check on `observed_at`.
- The normal repair scan stays as the backup for a lost event.
- Deploy: an older Central answers `unsupported event 'vm.network'` and drops the event. Central ships the handler before Atlas reruns `configure_state_webhooks`, which adds the delivery.

## Cargo reports

Cargo reports one service per delivery.

| Field | Required | Value |
|---|---|---|
| `service` | Yes | `telemetry`, `storage`, or `abuse` |
| `status` | For `telemetry` and `storage` | `Available` or `Not Available` |
| `service_endpoint` | No | The URL consumers reach the service at |

Planned: an `abuse` report carries the findings of Watcher, the Cargo abuse detection. It has a `findings` list, and no `status` or `service_endpoint`. Central handles it in its own branch of `accept_cargo_report`, before the status check, and writes no Service Detail row for it. The shape is in [Abuse protection](ABUSE.md#reports-from-cargo).

Cargo must map its own lifecycle states before it sends. Central records availability, not a Cargo state name. A cluster or host that is `Active` reports `Available`. Any other settled state reports `Not Available`.

A body may also carry `region` and `region_id`. Central ignores both. The region comes from `X-FC-Region`, which the signature covers.

Central writes one Service Detail row per region and service, named `<region>-<service>`. A repeated report rewrites that row. It does not make a second one.

```json
{"recorded": true, "service_detail": "ap-south-1-storage"}
```

## What Central refuses

| Condition | Answer |
|---|---|
| No `X-FC-Source`, or a value other than `atlas` or `cargo` | HTTP 403 |
| No `X-FC-Region` or no signature | HTTP 403 |
| Unknown region, disabled or unregistered region, no stored secret, or a signature mismatch | HTTP 403, `Invalid signature.` |

Retrying a refused delivery does not help. An operator must correct the region record or the shared secret first.

## What Central ignores

An ignored report is authentic and readable. Central has nothing to do with it. The answer is HTTP 200, so a sender does not retry.

```json
{"queued": false, "ignored": "no change"}
```

| Reason | Sender | Meaning |
|---|---|---|
| `unreadable body` | Both | The body is not a JSON object |
| `unknown server` | Atlas | No Virtual Machine in this region carries that VM ID |
| `unsupported event '<value>'` | Atlas | The event is not `vm.state` or `vm.state.deleted`. Planned: `vm.network` is also supported. |
| `unsupported status '<value>'` | Atlas | The status of a `vm.state` report is not `running`, `stopped`, or `paused` |
| `invalid observed_at` | Atlas | `observed_at` of a `vm.state` report is missing or is not a timestamp |
| `no change` | Atlas | Central already records this state, or the server of a `vm.state.deleted` report is already `Terminated` |
| `stale report` | Atlas | `observed_at` is not newer than the last report Central applied |
| `unsupported service '<value>'` | Cargo | The service is not `telemetry`, `storage`, or `abuse` |
| `unsupported status '<value>'` | Cargo | The status of a `telemetry` or `storage` report is not `Available` or `Not Available` |

A region may report on a timer instead of on change. When a same-state report has a newer `observed_at`, Central advances `Virtual Machine.last_reported_at` and answers `no change`. This stops an older state change that arrives later from changing the server.

## Retries

Send again on a timeout or on any 5xx answer. Central applies an Atlas report under a row lock and discards a report older than the one it holds, so a repeated delivery is safe.

Do not retry a 403. Do not retry a 200, including an ignored one.

## Example

```http
POST /api/method/central.api.state_delivery.receive HTTP/1.1
Host: central.example.com
Content-Type: application/json
X-FC-Source: cargo
X-FC-Region: ap-south-1
X-Frappe-Webhook-Signature: 9Xq0k1m2n3o4p5q6r7s8t9u0v1w2x3y4z5A6B7C8D9E=

{"service": "storage", "status": "Available", "service_endpoint": "https://s3-svc.ap-south-1.example.com"}
```

## Where this lives in Central

| Part | File |
|---|---|
| Route and sender dispatch | `central/api/state_delivery.py` |
| Signature checks and handlers | `central/integrations/state_delivery.py` |
| Recorded service state | `central/services/doctype/service_detail/` |
