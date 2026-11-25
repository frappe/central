---
title: Connect an AI agent
description: Let Claude, Cursor, or another AI agent use Frappe Cloud through the Central MCP server.
---

# Connect an AI agent

An AI agent, such as Claude Code or Cursor, can use Frappe Cloud for you through MCP, the Model Context Protocol. The agent finds the operation it needs, reads its arguments, and runs it as you.

The agent can do only what your API key allows. It asks you before it runs an operation that changes data.

## What you need

- An API key and its secret. See [Get an API key](./api#get-an-api-key).
- [uv](https://docs.astral.sh/uv/), which runs the MCP server.
- A copy of the [frappe/central](https://github.com/frappe/central) repository.

## Add the server

Run this in Claude Code. Replace the URL, key, and secret with your own:

```bash
git clone https://github.com/frappe/central.git
claude mcp add central \
  -e CENTRAL_URL=https://<your Frappe Cloud URL> \
  -e CENTRAL_API_KEY=<api key> \
  -e CENTRAL_API_SECRET=<api secret> \
  -- uv run --directory "$PWD/central" --with-requirements mcp_server/requirements.txt mcp_server/server.py
```

Other agents take the same command and the same three variables in their MCP settings.

## Check the connection

In Claude Code, type `/mcp`. The `central` server shows three tools:

| Tool | What it does |
| --- | --- |
| `search_operations` | Finds operations by words, such as `team members` |
| `get_operation` | Shows the arguments of one operation and whether it changes data |
| `call_operation` | Runs one operation as you |

Then ask the agent a question, such as "Which servers does my team have, and are they running?"

## What the agent reads

When the server starts, it reads the [API reference](https://frappe.github.io/central/api/) and a short guide for agents at `/assets/central/agents.md` from your Frappe Cloud URL. A new operation appears for the agent as soon as your Frappe Cloud site has it.
