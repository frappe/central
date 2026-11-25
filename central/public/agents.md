# Central for AI agents

Central is the control plane for Frappe Cloud v2. It owns teams, servers, sites, snapshots, SSH keys, WireGuard devices and support tickets.

- Read the operations in the OpenAPI document at `/assets/central/openapi.json`. People read the same document at `/central/api`.
- Send `Authorization: token <api key>:<api secret>` with every call. The capabilities of that user decide what succeeds. A refusal is the answer for that user, not a fault.
- Pass `team` to every operation that takes it. Read it from `identity.my_teams` or ask the person. Do not guess it.
- An operation whose description ends in `Changes data.` changes the team's servers, sites, members or billing. Ask the person before you run one.
- `support.create_ticket` opens a real ticket with Frappe Cloud support. Read the allowed `category` and `issue_type` values from `support.get_ticket_options` first.
