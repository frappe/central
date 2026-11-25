# Central API

## Purpose

This document describes the customer API of Central and how to read it.
The OpenAPI 3.1 document is generated from the code. No hand edit survives a regeneration.

## What is documented

The generator reads the whitelisted functions in `central/api/` for 11 modules, listed with their reference names in `DOCUMENTED_MODULES`: activity, firewall_rulesets, identity, images, servers, sites, snapshots, ssh_keys, support, teams, and wireguard. Grove is left out because every Grove endpoint is a machine endpoint.

Each function becomes one path, `/api/method/central.api.<module>.<function>`, with an operationId of `<module>.<function>`.
The operation takes the function signature as query parameters when the function allows GET, and as a JSON request body otherwise.
The document declares one security scheme: the `Authorization` header with `token <api key>:<api secret>`. The capabilities of the token's user decide access.

Every operation declares the responses `200`, `401`, and `403`. Every operation declares an `x-mcp` object. `requires_team` is true when the function takes a `team` argument. `read_only` is true when the function allows GET. Every description ends with `Read-only.` or `Changes data.`, so a tool can state the effect of a call before it runs.

`central/www/central/api.py` serves the Scalar reference at `/central/api`. The page loads the document from `/assets/central/openapi.json`. A signed-in client can read the same document from `central.api.openapi.document`. The committed file at `central/public/openapi.json` is for download and for drift checking, not for the page.

## What is excluded

Guest endpoints are excluded, because no token identifies the caller. The excluded modules are pilot, oidc, jwks, sso, signups, auth, state_delivery, and email_oauth.

Functions whose return value is not JSON are excluded, because a schema cannot describe them.

The built-in `/api/v2/mcp` endpoint is the MCP surface for Desk users. It is not part of this document.

## MCP server

`mcp_server/server.py` is a stdio MCP server for any token user. It reads this document from `central.api.openapi.document` at start, so it never drifts from the deployed API. It also reads the agent guide at `/assets/central/agents.md` (`central/public/agents.md`) and gives it to the agent as its instructions. It exposes three tools: `search_operations`, `get_operation`, and `call_operation`. `mcp_server/README.md` gives the environment variables.

## Customer docs

The customer docs in `docs/content/developers/` explain how to use the API and connect an agent. `yarn api` in `docs/` copies `central/public/openapi.json` into the site, and `docs/content/public/api/index.html` renders it at `https://frappe.github.io/central/api/`.

## Regenerate

Run the bench python, `../../env/bin/python scripts/generate_openapi.py` from the app directory, after you change a documented function or a docstring. The script rewrites `central/public/openapi.json` and prints the path and the operation count.

## Validation

Run `central.tests.test_openapi`. The test fails when the committed document is stale, when a path comes from a guest endpoint, when an operation lacks a summary, a description or a unique operationId, when an operation lacks the three responses or the `x-mcp` object, when a description does not end with its data change note, when `requires_team` disagrees with the declared `team` argument, or when the document holds fewer than 60 operations.
