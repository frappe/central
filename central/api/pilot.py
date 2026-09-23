from __future__ import annotations

import functools
from collections.abc import Callable

import frappe
from frappe import _

from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.site_domain.site_domain import SiteDomain
from central.services.doctype.service_detail.service_detail import ServiceDetail

TELEMETRY = "telemetry"

# The pilot→Central surface. The pilot (the on-VM agent, ~/pilot) authenticates with
# the opaque token Central minted for it (stored in the bench's bench.toml).
# The token rides an X-Pilot-Token header, NOT Authorization: Frappe's validate_auth()
# claims the Authorization header and 401s any scheme it can't map to a real user,
# before an allow_guest endpoint runs. The decorator resolves the token to its Pilot
# Credential and exposes it on frappe.local so handlers know who they serve.

TOKEN_HEADER = "X-Pilot-Token"


def pilot_credential_auth(func: Callable) -> Callable:
	"""Authenticate a pilot by its X-Pilot-Token. Exposes the resolved credential on
	frappe.local.pilot_credential; rejects a missing/unknown/revoked/expired token with
	401. Sits under @frappe.whitelist(allow_guest=True)."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		credential = PilotCredential.verify(frappe.get_request_header(TOKEN_HEADER) or "")
		if not credential:
			frappe.throw(_("Invalid or expired pilot credential."), frappe.AuthenticationError)
		frappe.local.pilot_credential = credential
		return func(*args, **kwargs)

	return wrapper


def get_pilot_region(credential: PilotCredential) -> str | None:
	"""The region this pilot runs in, or None while Atlas has not bound its VirtualMachine.
	`VirtualMachine.cluster` is a Region, so the region needs no lookup of its own."""
	if not credential.server:
		return None

	return frappe.db.get_value("Virtual Machine", credential.server, "cluster", cache=True)


def get_telemetry_base_url(region: str | None) -> str | None:
	"""Where one region takes metrics and logs, or None until its telemetry host reports.

	The region's own report is the only thing that knows this, and it stops being handed
	out the moment that host reports itself down."""
	return ServiceDetail.endpoint_for(region, TELEMETRY) if region else None


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def heartbeat() -> dict:
	"""Liveness + identity probe: proves a pilot can reach and authenticate to Central,
	and reports which team/pilot Central resolved it to."""
	credential = frappe.local.pilot_credential

	return {
		"ok": True,
		"team": credential.team,
		"pilot_credential_id": credential.pilot_credential_id,
		"server_time": frappe.utils.now(),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def config() -> dict:
	"""Discovery the pilot pulls on boot (and refreshes on a TTL): where Central's JWKS
	lives and this deployment's audience id — all a bench needs to verify minted tokens.
	No issuer is returned: it is Central's own URL (the same host the pilot already calls),
	and the bench binds tokens by signature + audience, not issuer."""
	from central.sso import jwks_url

	credential = frappe.local.pilot_credential
	return {"jwks_url": jwks_url(), "audience_id": credential.audience_id}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def datum_token() -> dict:
	"""The JWT this pilot presents to Datum, for metrics and for logs alike.

	Separate from `config` because it expires: the pilot re-fetches on a 401 or when
	the expiry nears. Refused until Atlas binds the VirtualMachine, since the rows would carry
	no resource id."""
	from central.sso import DATUM_TTL, mint_datum_token

	credential: PilotCredential = frappe.local.pilot_credential
	region = get_pilot_region(credential)

	return {
		"token": mint_datum_token(region_id_of(region), credential.server),
		"expires_in": DATUM_TTL,
		"resource_id": credential.server,
		"endpoint": get_telemetry_base_url(region),
	}


# TODO: This hack should goaway once region id is integrated into the region doctype
def region_id_of(region: str | None) -> int:
	"""The Atlas region id the token's audience names. A pilot with no region yet has no
	datum to write to, so it is refused here rather than handed a token nothing accepts."""
	if not region:
		frappe.throw(
			_("This pilot has no region yet; a datum token would name no host."),
			frappe.ValidationError,
		)

	return frappe.get_doc("Region", region).get_atlas_region_id()


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def domain_records(domain: str) -> dict:
	"""DNS records to set before `register_domain`. Empty for a site in the regional zone."""
	return SiteDomain.get_dns_records(frappe.local.pilot_credential, domain)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def register_domain(domain: str) -> None:
	"""Route a site or a verified custom domain to this Pilot's server."""
	SiteDomain.register(frappe.local.pilot_credential, domain)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def deregister_domain(domain: str) -> None:
	"""Remove a route of this Pilot's server."""
	SiteDomain.deregister(frappe.local.pilot_credential, domain)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def enroll(bootstrap_token: str) -> dict:
	"""First-boot handshake: exchange a single-use, create-time bootstrap token for this
	pilot's long-lived credential plus its discovery config — in one call. The bootstrap
	token (signed by Central, short-lived, single-use) is the only authentication; the
	pilot has no credential yet."""
	from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
	from central.sso import BOOTSTRAP_TTL, central_url, jwks_url, verify_bootstrap_token

	grant = verify_bootstrap_token(bootstrap_token)

	# Single-use: atomically claim the token's jti before minting, so a replay (the token
	# leaking from VM metadata) — or two concurrent enrolments racing — can't both succeed
	# and rotate a live pilot's credential out from under it. SETNX is atomic; a check-then-set
	# would leave a window where both callers pass. Keyed via make_key so it stays site-scoped.
	consumed_key = frappe.cache.make_key(f"pilot:enroll:consumed:{grant['jti']}")
	if not frappe.cache.set(consumed_key, 1, nx=True, ex=BOOTSTRAP_TTL):
		frappe.throw(_("This enrollment token has already been used."), frappe.AuthenticationError)

	# The pilot_credential_id is this bench's audience id: every downward token Central mints
	# for it carries `aud = pcid`, and the bench verifies against it. issue_for preserves any
	# VirtualMachine link the VM events already bound (billing reads it) — enrollment only mints the token.
	try:
		token = PilotCredential.issue_for(
			team=grant["team"], pilot_credential_id=grant["pcid"], audience_id=grant["pcid"]
		)
		# Commit before returning: a rollback of this request must not strand the pilot with a
		# token Central will not recognise.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- commit before returning
	except Exception:
		frappe.cache.delete(consumed_key)
		raise

	return {
		"auth_token": token,
		"central_endpoint": central_url(),
		"jwks_url": jwks_url(),
		"audience_id": grant["pcid"],
	}
