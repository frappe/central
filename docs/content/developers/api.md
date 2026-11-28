---
title: Use the API
description: Manage your team's servers, snapshots, keys and support tickets from a script or another app with an API key.
---

# Use the API

You can manage your team from a script or from another app. The API covers servers, images, snapshots, firewall rules, SSH keys, WireGuard devices, team members, activity and support tickets.

## Open the API reference

The [API reference](https://frappe.github.io/central/api/) lists every public operation. For each operation it shows the arguments, the answer, and if the operation changes data. Each Frappe Cloud site also shows its own reference at `/central/api`.

An operation whose description ends in **Changes data.** changes your team's resources. The other operations only read.

The reference shows only the operations that are meant for you. Steps that only the console uses, such as the trial signup, are not in it and can change without notice.

## Get an API key

Open **Settings > Access > API Keys** in the console and click **Add API key**. Choose:

| Setting | Meaning |
| --- | --- |
| Team | The only team the key acts on. |
| Expiration | 1, 7, 30, 90 or 365 days. |
| Permissions | **Servers**: Read or Write. **Support**: Write. **Read only** and **Full access** set both at once. |

The key never does more than your role in the team allows. It cannot manage team members, billing or other API keys, and it cannot open a server console.

The console shows the key once, as `<api key>:<api secret>`. Copy it then. If you lose it, revoke it and add another. Keep it private: anyone with it can act as you on that team.

## Read data

Send the key in the `Authorization` header, and `API Key` in the `Frappe-Authorization-Source` header. A read is a `GET` request with the arguments in the query string.

```bash
curl https://<your Frappe Cloud URL>/api/method/central.api.identity.my_teams \
  -H "Authorization: token <api key>:<api secret>" \
  -H "Frappe-Authorization-Source: API Key"
```

The answer is JSON. The result is in `message`:

```json
{"message": [{"name": "TEAM-00001", "label": "Acme", "role": "Owner", "members": 4, "status": "Active"}]}
```

Most operations need a `team` argument. Use the `name` that `central.api.identity.my_teams` returns.

```bash
curl "https://<your Frappe Cloud URL>/api/method/central.api.servers.registry?team=TEAM-00001" \
  -H "Authorization: token <api key>:<api secret>" \
  -H "Frappe-Authorization-Source: API Key"
```

Yes or no values are `true` or `false`.

## Change data

A change is a `POST` request with the arguments in a JSON body:

```bash
curl -X POST https://<your Frappe Cloud URL>/api/method/central.api.servers.stop_server \
  -H "Authorization: token <api key>:<api secret>" \
  -H "Frappe-Authorization-Source: API Key" \
  -H "Content-Type: application/json" \
  -d '{"team": "TEAM-00001", "resource_id": "<resource_id from registry>"}'
```

## Follow a server action

Creating, starting, stopping, resizing and terminating a server take time. These operations do not wait. They return the action that does the work:

```json
{"message": {"action": "8n4ve1k2qd", "status": "Queued", "resource_id": "vm-8f2c", "title": "web-1", "error": null}}
```

Read the action again with `central.api.servers.action_status`, with `name` set to the `action` value, until the status is final:

| Status | Meaning |
| --- | --- |
| `Queued`, `Dispatching`, `Sent`, `In Progress`, `Uncertain` | The action is not finished. Read it again in a few seconds. |
| `Succeeded` | The action is done. |
| `Failed`, `Timed Out` | The action stopped. `error` tells you why. Some failed actions can run again with `central.api.servers.retry_action`. |

## Errors

| Status | Meaning |
| --- | --- |
| `401` | The key or the secret is wrong, the key expired, or the `Frappe-Authorization-Source` header is missing. |
| `403` | Your role or the key's permissions do not allow this operation on this team. |
| `404` | The team, server or other record does not exist, or you cannot see it. |
| `417` | An argument is not valid, for example an unknown ticket category. |
| `429` | Too many requests. Wait, then try again. |

The body of an error names it in `exc_type`. The message for a person is in `_server_messages`, which is a JSON string.
