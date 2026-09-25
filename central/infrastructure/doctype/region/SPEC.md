# Regional configuration

## Purpose

Region is Central's one record for a region: its customer-facing identity (code, display
name, geography), and its connection to the Atlas that runs it (endpoint, numeric ID,
signed-access health). The numeric ID comes from Atlas Settings and defines the token
audience for every regional service — Atlas, Cargo, and the Proxy all mint against it.

## Configuration

Set `base_url` to the direct Atlas address and `atlas_region_id` to the verified value from
0 through 65535. The identifier uses a Data field so blank and valid region zero remain
distinct. Validation normalizes it to decimal form, and the controller adds a unique
database constraint.

Set `proxy_domain` to the wildcard zone the regional proxy serves, without the leading `*.`,
such as `par-2.fc.frappe.dev`. Central builds a server's bench gateway from it as
`https://admin-vm-<label>.<proxy_domain>`. The label is the VM's mesh address encoded the
way the regional automatic proxy decodes it: the six hextets after the mesh prefix as one
base-36 number, VM identity above tenant. The tenant API does not publish the zone, so the
value is operator-entered and verified like the numeric region ID. A blank zone leaves
servers without a gateway, and one-click Open stays unavailable.

The regional client requires HTTPS. HTTP is allowed only for localhost addresses when
Central developer mode is enabled. Embedded credentials, queries, and fragments are
refused. Requests do not follow redirects or retry automatically.

Initialize Central's [Atlas signing key](../central_sso_settings/SPEC.md) and configure its
public endpoint in Atlas before testing the connection. Regional reads use the signed
tenant API at `/api/atlas`. They do not use the admin API key or Central tunnel address.

## Operation

**Test Connection** is an operator action. It calls the image list with a Central token and
the system tenant header. It requires a valid image-list response. A generic Framework
ping does not prove regional authentication. It only reads from Atlas: it records
`reachable`, `connection_checked_at`, and `connection_error`, and never changes Atlas's own
configuration. A timeout, rejected credential, invalid response, or missing regional
configuration leaves a readable failure on the record. The saved configuration is locked
during the check so another edit cannot receive a stale result.

**Enroll Atlas** is a separate operator action, shown only on the Atlas tab. It points
Atlas's virtual-machine-state deliveries at Central's receiver (`PUT /api/atlas/webhooks`),
minting `webhook_secret` the first time it runs and reusing it after. The payload's
`central_id` comes from `Central Settings.central_id` (default 1) and is only worth
raising where more than one Central environment shares an Atlas — Atlas itself refuses
anything but 1 outside developer mode. Run it after Test Connection succeeds; it does not
itself prove Atlas is reachable. A failure raises and shows in the Desk like any other
action; nothing about it is recorded on the record itself. After Atlas is enrolled, it registers the region's Cargo when Cargo already answers. See [Registration](#registration).

Changing the endpoint or numeric region ID clears the connection result. Image offerings
read the regional catalog on demand.

The integration client also has a Team read path. It checks `server:view` through Central
IAM and reads the tenant ID from the authorized Team. The operator path is the only path
that selects system tenant zero.

`central.api.servers.list_instances` — the console's region picker — reads only the
non-secret allowlist (`region`, `status`, `reachable`, and the display fields). `base_url`,
`atlas_region_id`, and `webhook_secret` never leave a System Manager session.

## Scope and Cargo

Cargo also connects through this record, in its own `cargo_*` fields, under the Cargo tab. Atlas builds Cargo in the region and gives it its own credentials to call Atlas and the Proxy. Atlas installs Cargo with a placeholder Central URL and delivery secret, so Cargo reports nothing until Central registers it. Central needs three values: the Cargo address, `cargo_status`, and `cargo_webhook_secret`, which verifies Cargo's service reports in `central.integrations.state_delivery.accept_cargo_report`.

`Region.get_cargo_url` gives the Cargo address. It is `cargo_base_url` when an operator sets it, for example `http://10.0.0.5:8000` in development. Otherwise it is `https://cargo.<region>.<wildcard domain>`, where Atlas serves every Cargo it builds.

### Registration

`register_cargo` checks `/api/method/ping` at the Cargo address. When Cargo answers `pong`, Central sends it a fresh `cargo_webhook_secret` and Central's receiver URL through `cargo.api.webhooks.configure`, and sets `cargo_status` to Registered. A repeat only replaces the secret, so it is safe to retry. `accept_cargo_report` refuses every report until then.

| Trigger | When Cargo answers | When Cargo does not answer or refuses |
|---|---|---|
| **Enroll Atlas** | Atlas and Cargo are both enrolled. | Atlas stays enrolled. A refusal leaves an Error Log on the Region. The Desk says Central retries. |
| `register_pending_cargo`, every 10 minutes | Cargo becomes Registered. | Cargo stays Draft. A refusal leaves an Error Log on the Region. |
| **Enroll Cargo** on the Cargo tab | Cargo becomes Registered. | The action fails and shows the reason in the Desk. |

The sweep checks only Active regions whose Atlas is enrolled and whose Cargo is Draft, because Atlas does not report when Cargo is up. A Disabled Cargo is never registered automatically. After registration, Cargo reports its storage cluster, and Central records the region's storage Service Detail.

Atlas and Cargo are not peers: Cargo is created by Atlas and depends on it being there
first. That asymmetry is a fact about provisioning, not about where Central keeps its own
bookkeeping — both connections live on Region, each behind its own mixin
(`AtlasConnectionMixin` in `atlas_connection.py`, `CargoConnectionMixin` in
`cargo_connection.py`), so the two stay easy to tell apart in the code and never share a
field.

## Migration

`reset_atlas_connection_checks` clears reachability values without an authenticated check
timestamp. It does not guess numeric region IDs, rotate keys, or create remote resources.
Repeating the patch preserves checks with a timestamp.

Region absorbed the connection fields that used to live on separate Atlas Instance and Cargo Instance records. `Virtual Machine.region` and `Resource Action.region` link directly to Region. Billing keeps its own `cluster` price dimension. There is no second infrastructure record to join through.

The `rename_region_fields` patch copies values from the former Virtual Machine `cluster` and Resource Action `atlas_instance` columns after schema sync, then removes those columns. A repeat or partially applied run skips each missing source column.

## Scope and validation

The signed client in `central.integrations.atlas` owns regional image reads, VM creation,
VM reads, and power operations. [Resource Action](../resource_action/SPEC.md) owns their
durable request and recovery state.

Run `central.tests.test_regional_configuration` for request headers, tenant boundaries,
malformed responses, failure recording, and configuration invalidation. Real regional
acceptance remains pending until staging is ready.
