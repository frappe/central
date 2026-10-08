# AI

## Purpose

Central sells AI served by Grove. A team with AI is one Central Team at Grove, named by the team id. Grove owns the models, the rate limits, the usage and the API keys, and each key carries its own policy: the geography it works in, the models it may call, its rate limits, and the cap it may spend out of the team's balance. Central keeps no key: a key's secret is shown once, in the answer that mints it.

## Configuration

AI Settings holds the Grove URL and Central's control credential. A System Manager sets **Grove URL** and selects **Enroll** with the bootstrap secret Grove was given. Grove mints Central's control user and key (`grove.api.create_control_client`), and Central stores them. Enroll is a plain whitelisted call, not a form method, so the secret arrives at the top of the request and is popped before anything logs it. **Rotate Credential** asks Grove for a new secret under the current one (`grove.api.create_control_client_key`); the old one stops at once.

## Operation

- **Turning AI on**: `central.services.api.ai.enable_ai(team)` inserts a Team Service with `add_on_service = "ai"`. Its `before_insert` checks the team has no AI yet, then registers it at Grove (`provision_team`), so a refusal there leaves no row. `enable` locks the Team row, so two enables at once make one service. An `ai` row has no region, no subscription and no endpoint: AI is prepaid at Grove, and each key calls its own geography's gateway. A team has one.
- **Keys**: `list_api_keys`, `create_api_key`, `update_api_key` and `revoke_api_key` pass through to Grove with `team`. Only `create_api_key` returns a secret. A key is minted in a geography (one of `get_ai().geographies`; Grove's default when none is picked), with a cap in USD cut from the team's balance; a prepaid team's key needs a cap above zero, and Grove refuses one without. The geography never changes: a team spans geographies by minting a key in each. `update_api_key` changes the cap; Grove refuses one the balance cannot cover, since across a team's live keys the caps together never exceed the balance. Each key has its own rate limits (Grove's defaults: 20 requests and 100 000 tokens a minute) and the models it may call (`get_api_key_models`), decided at Grove. Grove refuses a key another team holds, refuses to revoke a key younger than six hours (it lists each key's `revocable_at`, and the console holds Revoke back until then rather than asking), and caps how many live keys a team holds.
- **Models**: `get_models(team, geography)` lists what a key in a geography starts with (the published models of Grove's default group there), for the overview; `get_api_key_models` lists what one key may call.
- **Balance, usage**: `get_ai` carries the team's balance — with `unallocated`, the part no key's cap has claimed yet — and this month's requests, tokens and cost, asked of Grove on every page open, uncached, so it matches the usage page. `get_usage` reads a period from Grove; usage of one key is narrowed by the key's hash, which Grove lists with it.
- **Alert address**: the team's Billing Profile email when set, else the owner's. `central.services.ai.on_alert_address_update` (a Team and Billing Profile hook) sends a change to Grove.
- **Billing**: Grove is prepaid and does its own metering. Central pulls nothing on a schedule; usage is read when a page asks.
- **Credit**: `add_credit(team, amount, reference)` is operator only and charges the team nothing; the team hands it to keys by raising their caps.

`central.integrations.grove.GroveClient` is the only code that calls Grove.
