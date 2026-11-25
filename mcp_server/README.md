# Central MCP server

A stdio MCP server over Central's API. It reads the OpenAPI document and the agent guide
(`/assets/central/agents.md`) from the site at start, so it never drifts from the deployed API.
Customer setup steps are in `docs/content/developers/agents.md`.

```bash
export CENTRAL_URL=https://central.example.com
export CENTRAL_API_KEY=...
export CENTRAL_API_SECRET=...
uv run --with-requirements mcp_server/requirements.txt mcp_server/server.py
```

Three tools:

| Tool | Use |
| --- | --- |
| `search_operations` | find an operation by words in its id, summary, description or tag |
| `get_operation` | read its arguments and whether it changes data |
| `call_operation` | run it as the token's user |

The token user's capabilities decide what succeeds. Team-scoped operations require `team`.
