# AI

## Purpose

Central sells AI served by Grove. A team with AI is one Grove user, named by the team id. Grove owns the models, the rate limits, the usage and the API keys. Central keeps no key: a key's secret is shown once, in the answer that mints it.

## Configuration

AI Settings holds the Grove URL and Central's control credential. A System Manager sets **Grove URL** and selects **Enroll** with the bootstrap secret Grove was given. Grove mints Central's control user and key (`grove.api.create_control_client`), and Central stores them. The secret is popped from the request, so it is never logged.

## Operation

- **Turning AI on**: `central.services.api.ai.enable_ai(team)` inserts a Team Service with `add_on_service = "ai"`. Its `before_insert` registers the team at Grove (`provision_user`) with the team owner's email for alerts, so a refusal there leaves no row. Grove pins the user to its default geography. An `ai` row has no region and no subscription: AI is prepaid at Grove. A team has one.
- **Keys**: `list_api_keys`, `create_api_key` and `revoke_api_key` pass through to Grove with `user = team`. Only `create_api_key` returns a secret. Grove refuses a key another team holds, and refuses to revoke a key younger than six hours.
- **Models, limits, usage**: `get_ai` and `get_usage` read them from Grove. Usage of one key is narrowed by the key's hash, which Grove lists with it.
- **Owner change**: `central.services.ai.on_team_update` sends the new owner's email to Grove.
- **Billing**: `central.services.ai.pull_usage` runs hourly and reports each AI team's monthly billable tokens to the `Tokens` meter.
- **Credit**: `add_credit(team, amount, reference)` is operator only and charges the team nothing.

`central.integrations.grove.GroveClient` is the only code that calls Grove.
