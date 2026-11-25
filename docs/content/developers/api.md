---
title: Use the API
description: Call the Frappe Cloud API from a script or another app with an API key, and find every operation in the API reference.
---

# Use the API

Everything the console does for a team, such as list servers, resize a server, or open a support ticket, is also an API call. You can make the same calls from a script or from another app.

## Open the API reference

The [API reference](https://frappe.github.io/central/api/) lists every operation, its arguments, and whether it changes data. Each Frappe Cloud site also shows its own reference at `/central/api`.

Operations are grouped by area, such as **Servers**, **Teams**, and **Support**. An operation whose description ends in **Changes data.** changes your team's resources. The others only read.

## Get an API key

An API key and its secret act as you. They can do what your role in the team allows, and nothing more.

The console does not create API keys yet. To get one, contact support.

Keep the secret private. Anyone with the key and the secret can act as you.

## Make a call

Send the key and the secret in the `Authorization` header:

```bash
curl https://<your Frappe Cloud URL>/api/method/central.api.identity.my_teams \
  -H "Authorization: token <api key>:<api secret>"
```

The answer is JSON. The result is in `message`.

Most operations need a `team` argument. Get your team names from `central.api.identity.my_teams` first.

A call that your role does not allow answers with status `403`. A call without a valid key answers with status `401`.
