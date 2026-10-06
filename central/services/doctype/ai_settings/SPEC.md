# AI

## Purpose

Central sells AI served by Grove. A team with AI is one Grove user, named by the team id. Grove owns the models, the rate limits, the usage and the API keys. Central keeps no key: a key's secret is shown once, in the answer that mints it.

## Configuration

AI Settings holds the Grove URL and Central's control credential. A System Manager sets **Grove URL** and selects **Enroll** with the bootstrap secret Grove was given. Grove mints Central's control user and key (`grove.api.create_control_client`), and Central stores them. Enroll is a plain whitelisted call, not a form method, so the secret arrives at the top of the request and is popped before anything logs it. **Rotate Credential** asks Grove for a new secret under the current one (`grove.api.create_control_client_key`); the old one stops at once.

## Operation

- **Turning AI on**: `central.services.api.ai.enable_ai(team)` inserts a Team Service with `add_on_service = "ai"`. Its `before_insert` checks the team has no AI yet, then registers it at Grove (`provision_user`), so a refusal there leaves no row. `enable` locks the Team row, so two enables at once make one service. Grove pins the user to its default geography and answers with that geography's endpoint, kept as the row's `endpoint_url`: the gateway every key of the team calls. An `ai` row has no region and no subscription: AI is prepaid at Grove. A team has one.
- **Keys**: `list_api_keys`, `create_api_key`, `revoke_api_key` and `set_api_key_balance_access` pass through to Grove with `user = team`. Only `create_api_key` returns a secret. A team's first key may read the team's credit at the gateway (`can_read_balance`, Grove's default); the switch on a key's row changes it. Grove refuses a key another team holds, and refuses to revoke a key younger than six hours: it lists each key's `revocable_at`, and the console holds Revoke back until then rather than asking.
- **Models, limits, usage**: `get_ai` and `get_usage` read them from Grove. `get_ai` also carries the team's balance and this month's requests, tokens and cost; the whole overview is cached per team for five minutes (`OVERVIEW_CACHE_SECONDS`), which loses nothing since Grove's own figures move at its hourly pull. Usage of one key is narrowed by the key's hash, which Grove lists with it.
- **Alert address**: the team's Billing Profile email when set, else the owner's. `central.services.ai.on_alert_address_update` (a Team and Billing Profile hook) sends a change to Grove.
- **Billing**: Grove is prepaid and does its own metering. Central pulls nothing on a schedule; usage is read when a page asks.
- **Credit**: `add_credit(team, amount, reference)` is operator only and charges the team nothing.

`central.integrations.grove.GroveClient` is the only code that calls Grove.
