# Regional configuration

## Purpose

Atlas Instance binds a Central Region to one Atlas endpoint and numeric Atlas region ID. Region names remain customer-facing identifiers. The numeric ID comes from Atlas Settings and defines the token audience.

## Configuration

Set `base_url` to the direct Atlas address and `atlas_region_id` to the verified value from 0 through 65535. The identifier uses a Data field so blank and valid region zero remain distinct. Validation normalizes it to decimal form, and the controller adds a unique database constraint.

Set `proxy_domain` to the wildcard zone the regional proxy serves, without the leading `*.`, such as `par-2.fc.frappe.dev`. Central builds a server's bench gateway from it as `https://admin-vm-<label>.<proxy_domain>`. The label is the VM's mesh address encoded the way the regional automatic proxy decodes it: the six hextets after the mesh prefix as one base-36 number, VM identity above tenant. The tenant API does not publish the zone, so the value is operator-entered and verified like the numeric region ID. A blank zone leaves servers without a gateway, and one-click Open stays unavailable.

The regional client requires HTTPS. HTTP is allowed only for localhost addresses when Central developer mode is enabled. Embedded credentials, queries, and fragments are refused. Requests do not follow redirects or retry automatically.

Initialize Central's [Atlas signing key](../central_sso_settings/SPEC.md) and configure its public endpoint in Atlas before testing the connection. Regional reads use the signed tenant API at `/api/atlas`. They do not use the admin API key or Central tunnel address.

## Operation

**Test Connection** is an operator action. It calls the image list with a Central token and the system tenant header. It requires a valid image-list response. A generic Framework ping does not prove regional authentication.

The action records `reachable`, `connection_checked_at`, and `connection_error`. A timeout, rejected credential, invalid response, or missing regional configuration leaves a readable failure on the record. The saved configuration is locked during the check so another edit cannot receive a stale result.

Changing the endpoint or numeric region ID clears the connection result. Image offerings read the regional catalog on demand.

The integration client also has a Team read path. It checks `server:view` through Central IAM and reads the tenant ID from the authorized Team. The operator path is the only path that selects system tenant zero.

## Migration

`reset_atlas_connection_checks` clears reachability values without an authenticated check timestamp. It does not guess numeric region IDs, rotate keys, or create remote resources. Repeating the patch preserves checks with a timestamp.

## Scope and validation

The signed client in `central.integrations.atlas` owns regional image reads, VM creation, VM reads, and power operations. [Resource Action](../resource_action/SPEC.md) owns their durable request and recovery state.

Run `central.tests.test_regional_configuration` for request headers, tenant boundaries, malformed responses, failure recording, and configuration invalidation. Real regional acceptance remains pending until staging is ready.
