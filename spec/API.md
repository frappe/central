# Central API

## Purpose

This document describes the customer API of Central and how to read it.
The OpenAPI 3.1 document is generated from the code. No hand edit survives a regeneration.

## What is documented

The public API is opt in. `PUBLIC_API` in `central/api/openapi.py` names each public endpoint, grouped by module with the name and description the reference shows. An endpoint that is not in this list is not documented, even when it is whitelisted. To publish an endpoint, add its name to `PUBLIC_API` and regenerate the document. The generator fails when a listed name is not a logged-in endpoint that answers JSON.

Each function becomes one path, `/api/method/central.api.<module>.<function>`, with an operationId of `<module>.<function>`.
The operation takes the function signature as query parameters when the function allows GET, and as a JSON request body otherwise.

## Request and response models

Each POST operation takes a named request model, `<Function>Request`, built from the function signature. Each operation returns a named response model in `message`. The response models are `TypedDict` classes in `central/api/models/` (`teams.py`, `servers.py`, `sites.py`), and the function's return hint names its model, for example `def list_team_members(team: str) -> list[TeamMember]`. `ActionStatus` and `AppRequirements` come from `central/server_models.py`. A change to a model is an API change, so review it as one. Frappe does not check return hints at runtime, so a model documents the answer and does not change it.
The document declares one security scheme: the `Authorization` header with `token <api key>:<api secret>`, sent with `Frappe-Authorization-Source: API Key`. A key acts on one team, within its permissions and its user's role. See [API Keys](IAM.md#api-keys).

Every operation declares the responses `200`, `401`, and `403`. Every description ends with `Read-only.` or `Changes data.`, so a reader knows whether a call changes data before running it.

`central/www/central/api.py` serves the Scalar reference at `/central/api`. The page loads the document from `/assets/central/openapi.json`. A signed-in client can read the same document from `central.api.openapi.document`. The committed file at `central/public/openapi.json` is for download and for drift checking, not for the page.

## What is excluded

These endpoints are not in `PUBLIC_API`:

| Endpoints | Why |
| --- | --- |
| Trial signup and onboarding: every endpoint in `central.api.sites`, `servers.keep_trial_site` and `teams.set_onboarding_step` | The console's signup flow. Their arguments follow its pages. |
| `identity.set_profile_photo` and `teams.set_team_logo` | They take the address of a file that the console uploaded first. |
| `support.find_related` | The console's search-as-you-type in the support dialog. |
| `servers.get_idle_sleep`, `servers.set_idle_sleep` and `servers.refresh_servers` | Sleep is for internal teams only, and refresh is a manual reconcile. |
| Staff actions: impersonate, suspend, unsuspend and restore a team | Their own checks refuse customers. |
| Guest endpoints: pilot, oidc, jwks, sso, signups, auth, state_delivery, email_oauth and grove | No token identifies the caller. |

## Customer docs

The customer docs in `docs/content/developers/` explain how to use the API. `yarn api` in `docs/` copies `central/public/openapi.json` into the site, and `docs/content/public/api/index.html` renders it at `https://frappe.github.io/central/api/`.

## Regenerate

Run the bench python, `../../env/bin/python scripts/generate_openapi.py` from the app directory, after you change a documented function or a docstring. The script rewrites `central/public/openapi.json` and prints the path and the operation count.

## Validation

Run `central.tests.test_openapi`. The test fails when an operation returns a bare `dict` instead of a named model, when the committed document is stale, when a path comes from a guest endpoint, when an operation lacks a summary, a description or a unique operationId, when an operation lacks the three responses, when a description does not end with its data change note, or when the document holds fewer than 60 operations.
